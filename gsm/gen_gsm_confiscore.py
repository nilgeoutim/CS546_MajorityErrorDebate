"""
This script is used to generate the GSM dataset with the Confidence Score built on basis of the majority error.


"""
import openai
import json
import numpy as np
import random
import re


# ======= Helper: extract number =======
def extract_number(text):
    """从文本中提取最后一个数字（包含整数/小数）。"""
    m = re.findall(r"[-+]?\d*\.?\d+", text)
    return m[-1] if m else None

# ========== Helper: extract explanation ==========
def parse_critic_explanation(text):
    """
    从 critic 输出中解析 Explanation 段，解析不到就返回原文本。
    """
    m = re.search(r"Explanation\s*:\s*(.*)", text, re.DOTALL)
    if not m:
        return text.strip()
    return m.group(1).strip()

# ========== Helper: extract confidencescore ==========
def parse_critic_score(text):
    m = re.search(r"Confidence\s*Score\s*:\s*([0-9]+)", text)
    if not m:
        return None
    score = int(m.group(1))
    return max(1, min(10, score))

# ======= Critic Prompt =======
def construct_critic_message(question, agent_answer):
    prompt = (
        "You are a math critic. Evaluate how sound the reasoning is and how likely the final answer "
        "is correct.\n\n"
        "Respond ONLY in this format:\n"
        "Confidence Score: <1-10>\n"
        "Explanation: <brief explanation>\n\n"
        f"Problem:\n{question}\n\n"
        f"Agent's reasoning and answer:\n```{agent_answer}```"
    )
    return [{"role": "user", "content": prompt}]

# ========== Debate Prompt (LLM 部分的规则) ==========
def construct_debate_prompt(question, your_ans, your_score, others):
    """
    构造 score-aware debate prompt（程序已处理 high-consensus 和 low-score）。
    这里只负责 normal case：score 高者 defend，score 低者 learn。
    """

    others_text = ""
    for j, obj in enumerate(others):
        others_text += f"Agent {j}: answer {obj['ans']}, score {obj['score']}\n"

    prompt = f"""
You are participating in a multi-agent debate assisted by a critic.

Here are the previous round's answers and confidence scores:

Your answer: {your_ans}, score: {your_score}
{others_text}

Based on these scores:

- If your score is significantly higher than others (e.g., >2 points higher), KEEP and DEFEND your reasoning.
- If your score is significantly lower, STUDY the highest-scoring agent’s answer and adjust accordingly.

Now provide your updated reasoning, ending with \\boxed{{answer}}.
"""
    return {"role": "user", "content": prompt}


# ========== Restart Prompt（所有 agent 分数都低） ==========
def construct_restart_prompt(question, critic_explanation):
    return {
        "role": "user",
        "content": (
            "The critic believes your previous reasoning was not correct.\n"
            f"Reason given by the critic: {critic_explanation}\n\n"
            "Please restart your reasoning from scratch and independently solve the problem:\n"
            f"{question}\n\n"
            "End with \\boxed{{answer}}."
        ),
    }


# ========== construct_message for multi-agent answers ==========
def construct_message(agents, question, idx):
    """
    仍使用你的原结构：从 other agents 中取 idx（上一轮 assistant）。
    idx 已经更新为 3*round - 2，保证指向 assistant。
    """
    if len(agents) == 0:
        return {
            "role": "user",
            "content": (
                "Can you double check your answer? Reiterate with \\boxed{{answer}}."
            ),
        }

    prefix_string = "These are the solutions from other agents:"

    for agent in agents:
        agent_response = agent[idx]["content"]
        prefix_string += f"\n\nOne agent solution: ```{agent_response}```"

    prefix_string += (
        f"\n\nUsing these solutions as additional info, answer the original problem:\n"
        f"{question}\nYour final answer must end with \\boxed{{answer}}."
    )
    return {"role": "user", "content": prefix_string}


# ========== Assistant Message ==========
def construct_assistant_message(completion):
    content = completion.choices[0].message.content
    return {"role": "assistant", "content": content}


# ========== Read JSONL ==========
def read_jsonl(path: str):
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]


# ===============================================================
#                       MAIN: Debate v2.5
# ===============================================================

if __name__ == "__main__":
    agents = 3
    rounds = 3
    random.seed(0)

    HIGH_THRESHOLD = 8   # high confidence for early stop
    LOW_THRESHOLD = 4    # low confidence triggers restart

    generated_description = {}

    questions = read_jsonl("gsm_hard.jsonl")
    # random.shuffle(questions)

    client = openai.OpenAI()

    for data in questions:    # demo run 10 questions
        question = data["question"]
        answer = data["answer"]

        # 初始化每个 agent context
        agent_contexts = [[
            {
                "role": "user",
                "content": (
                    f"Can you solve this math problem? {question}\n"
                    "Explain your reasoning and end with \\boxed{{answer}}."
                ),
            }
        ] for _ in range(agents)]

        for round in range(rounds):
            print(f"\n========== ROUND {round} ==========")

            # --- 每轮存储结果 ---
            answers_this_round = []
            scores_this_round = []
            critic_explanations_this_round = []

            # --- agent inference ---
            for i, agent_context in enumerate(agent_contexts):

                # 不是第一轮才参考其他 agent
                if round != 0:
                    idx = 3 * round - 2
                    agent_contexts_other = agent_contexts[:i] + agent_contexts[i+1:]
                    message = construct_message(agent_contexts_other, question, idx)
                    agent_context.append(message)

                # === Agent generation ===
                print("agent_num, agent_context: ", i, agent_context)
                completion = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=agent_context,
                    n=1,
                )
                assistant_msg = construct_assistant_message(completion)
                agent_context.append(assistant_msg)

                # Extract numeric answer
                ans_number = extract_number(assistant_msg["content"])
                answers_this_round.append(ans_number)

                # === Critic scoring ===
                critic_messages = construct_critic_message(
                    question, assistant_msg["content"]
                )
                critic_completion = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=critic_messages,
                    n=1,
                )
                critic_content = critic_completion.choices[0].message.content
                score = parse_critic_score(critic_content)
                score = score if score is not None else 1
                scores_this_round.append(score)
                
                critic_expl = parse_critic_explanation(critic_content)
                critic_explanations_this_round.append(critic_expl)

                # Append critic feedback (not used directly in v2.5 decisions)
                agent_context.append(
                    {"role": "user", "content": f"Critic score: {score}/10."}
                )

            # ----- Debug 输出 -----
            print(f"GT: {extract_number(answer)}")
            for i in range(agents):
                print(f"Agent {i}: answer={answers_this_round[i]}, score={scores_this_round[i]}")
            print("-----------------------------------")

            # ===================================================
            #           Early Stopping Conditions
            # ===================================================

            # ==== Condition A: High-consensus early stop ====
            if len(set(answers_this_round)) == 1 and all(
                s >= HIGH_THRESHOLD for s in scores_this_round
            ):
                print(">>> EARLY STOP: High-confidence consensus reached.")
                break

            # ==== Condition B: All agents low-confidence ====
            if all(s < LOW_THRESHOLD for s in scores_this_round):
                print(">>> RESTART: All agents low confidence. Force full rethinking next round.")

                # 下一轮强制 restart prompt
                for agent_context in agent_contexts:
                    agent_context.append(construct_restart_prompt(question))

                continue

            # ===================================================
            #      Normal Case: Construct Score-Aware Debate Prompt
            # ===================================================

            for i, agent_context in enumerate(agent_contexts):
                your_ans = answers_this_round[i]
                your_score = scores_this_round[i]

                # others
                others = []
                for j in range(agents):
                    if j != i:
                        others.append({
                            "ans": answers_this_round[j],
                            "score": scores_this_round[j]
                        })

                debate_prompt = construct_debate_prompt(
                    question, your_ans, your_score, others
                )
                agent_context.append(debate_prompt)

        # save logs
        generated_description[question] = (agent_contexts, answer)

    json.dump(generated_description, open("gsm_v2.5.json", "w"))

    print("\nSaved gsm_v2.5.json\n")
