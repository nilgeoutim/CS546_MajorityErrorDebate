"""
This script is used to generate the GSM dataset with the Confidence Score
built on basis of the majority error, using a multi-agent debate with a critic.
"""

import openai
import json
import numpy as np
import random
import re
import time
from tqdm import tqdm

# ======= Helper: extract number =======
def extract_number(text):
    """从文本中提取最后一个数字（包含整数/小数）。"""
    m = re.findall(r"[-+]?\d*\.?\d+", text)
    return m[-1] if m else None


# ========== Helper: extract explanation ==========
def parse_critic_explanation(text):
    """
    从 critic 输出中解析 Explanation 段，解析不到就返回原文本。
    约定 critic 输出格式大致为:
      Confidence Score: X
      Explanation: ...
    """
    m = re.search(r"Explanation\s*:\s*(.*)", text, re.DOTALL)
    if not m:
        return text.strip()
    return m.group(1).strip()


# ========== Helper: extract confidence score ==========
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


# ========== Unified Debate Prompt（正常情况：使用上一轮的 answer + score + reasoning） ==========
def construct_unified_debate_prompt(question, your_ans, your_score, your_solution, others):
    """
    统一的 debate prompt，合并了原来的 construct_message 和 construct_debate_prompt 逻辑。

    参数：
      question: 原题目
      your_ans: 当前 agent 上一轮的数值答案
      your_score: 当前 agent 上一轮的 critic score
      your_solution: 当前 agent 上一轮的完整 reasoning+answer 文本
      others: list[{"ans": ..., "score": ..., "solution": ...}] 其他 agent 的信息
    """

    others_text = ""
    for j, obj in enumerate(others):
        others_text += (
            f"One agent's answer:  ```{obj['solution']}```, its score is {obj['score']}/10\n"
        )

    prompt = f"""
You are participating in a multi-agent debate assisted by a critic.

Your previous reasoning and answer were:
```{your_solution}```, your score is {your_score}/10

Here are the previous round's answers and confidence scores from other agents:

{others_text}
Based on these scores:

- If your score is significantly higher than others, KEEP and DEFEND your reasoning and answer.
- If your score is significantly lower, STUDY the highest-scoring agent’s answer and adjust your reasoning accordingly.

Considering the above information, please provide your reasoning and answer to the original problem:
{question}

Your final answer must end with \\boxed{{answer}}.
"""
    return {"role": "user", "content": prompt}


# ========== Restart Prompt（所有 agent 分数都低） ==========
def construct_restart_prompt(question, critic_explanation, prev_solution, prev_answer, prev_score):
    """
    当所有 agent 的 score 都很低时，对单个 agent 使用的 restart prompt。
    这里显式提供：
      - 上一轮该 agent 的 reasoning（prev_solution）
      - 上一轮提取的 numeric answer（prev_answer）
      - 上一轮 critic 的 score（prev_score）
      - critic 的 explanation（critic_explanation）
    """
    prev_ans_str = prev_answer if prev_answer is not None else "N/A"

    return {
        "role": "user",
        "content": (
            "The critic believes your previous reasoning was not correct.\n\n"
            "Your previous reasoning and answer were:\n"
            f"```{prev_solution}```\n"
            f"Your extracted answer was: {prev_ans_str}, and the critic gave it a confidence score of {prev_score}/10.\n\n"
            f"Reason given by the critic: {critic_explanation}\n\n"
            "Please restart your reasoning from scratch and independently solve the problem:\n"
            f"{question}\n\n"
            "Do not simply repeat your previous solution; carefully re-derive the answer step by step.\n"
            "End with \\boxed{{answer}}."
        ),
    }


# ========== Assistant Message ==========
def construct_assistant_message(completion):
    content = completion.choices[0].message.content
    return {"role": "assistant", "content": content}


# ========== Read JSONL ==========
def read_jsonl(path: str):
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]


# ===============================================================
#                       MAIN
# ===============================================================

if __name__ == "__main__":
    agents = 3
    rounds = 4
    sample_count = 100
    random.seed(0)

    HIGH_THRESHOLD = 7   # high confidence for early stop
    LOW_THRESHOLD = 7    # low confidence triggers restart

    generated_description = {}

    questions = read_jsonl("gsm_majority_error.jsonl")
    # random.shuffle(questions)

    client = openai.OpenAI()

    # 记录开始时间
    start_time = time.time()

    for data in tqdm(questions[:sample_count], desc="Processing samples", total=sample_count):
        question = data["question"]
        answer = data["answer"]

        # 初始化每个 agent context（第一次 debate 的起点）
        def init_agent_contexts():
            return [[
                {
                    "role": "user",
                    "content": (
                        f"Can you solve this math problem? {question}\n"
                        "Explain your reasoning and end with \\boxed{{answer}}."
                    ),
                }
            ] for _ in range(agents)]

        agent_contexts = init_agent_contexts()
        round_idx = 0

        while round_idx < rounds:
            # print(f"\n========== ROUND {round_idx + 1} ==========")

            # --- 每轮存储结果 ---
            answers_this_round = []
            scores_this_round = []
            critic_explanations_this_round = []
            solutions_this_round = []  # 保存每个 agent 本轮的完整 reasoning+answer 文本

            # --- agent inference ---
            for i, agent_context in enumerate(agent_contexts):

                # === Agent generation ===（stateless：只给最后一条 user prompt）
                # print("agent_num, prompt: ", i, last_user_msg["content"])

                completion = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=agent_context,
                    n=1,
                )
                assistant_msg = construct_assistant_message(completion)
                agent_context.append(assistant_msg)

                # 保存完整 reasoning 文本
                solutions_this_round.append(assistant_msg["content"])

                # Extract numeric answer
                ans_number = extract_number(assistant_msg["content"])
                answers_this_round.append(ans_number)

                # === Critic scoring ===
                critic_messages = construct_critic_message(
                    question, assistant_msg["content"]
                )
                # print("critic_messages: ", critic_messages)
                critic_completion = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=critic_messages,
                    n=1,
                )
                critic_content = critic_completion.choices[0].message.content
                score = parse_critic_score(critic_content)
                score = score if score is not None else 5
                scores_this_round.append(score)

                critic_expl = parse_critic_explanation(critic_content)
                # print("critic_expl: ", critic_expl)
                critic_explanations_this_round.append(critic_expl)

            # ----- Debug 输出 -----
            # print(f"GT: {extract_number(answer)}")
            # for i in range(agents):
            #     print(f"Agent {i}: answer={answers_this_round[i]}, score={scores_this_round[i]}")
            # print("-----------------------------------")

            #           Early Stopping Conditions:
            #           Condition A: High-consensus early stop
            if len(set(answers_this_round)) == 1 and all(
                s >= HIGH_THRESHOLD for s in scores_this_round
            ):
                # print(">>> EARLY STOP: High-confidence consensus reached.")
                break

            # ==== Condition B: All agents low-confidence ====
            if all(s < LOW_THRESHOLD for s in scores_this_round):
                # print(">>> RESTART: All agents low confidence. Restart 3-round debate from scratch.")

                # 1) 对每个 agent 构造带 explanation + 上一轮 reasoning/answer 的 restart prompt
                new_agent_contexts = []
                for i in range(agents):
                    expl = critic_explanations_this_round[i]
                    prev_sol = solutions_this_round[i]
                    prev_ans = answers_this_round[i]
                    prev_score = scores_this_round[i]
                    new_agent_contexts.append([
                        construct_restart_prompt(
                            question,
                            expl,
                            prev_sol,
                            prev_ans,
                            prev_score,
                        )
                    ])

                agent_contexts = new_agent_contexts
                # 2) 重置轮数，从 0 再来 3 轮
                round_idx = 0
                continue  # 进入下一轮（新的一轮）

            # ===================================================
            #      Normal Case: Construct Unified Score-Aware Debate Prompt
            # ===================================================

            for i, agent_context in enumerate(agent_contexts):
                your_ans = answers_this_round[i]
                your_score = scores_this_round[i]
                your_solution = solutions_this_round[i]

                # 其他 agents 的 answer + score + reasoning
                others = []
                for j in range(agents):
                    if j == i:
                        continue
                    others.append({
                        "ans": answers_this_round[j],
                        "score": scores_this_round[j],
                        "solution": solutions_this_round[j],
                    })

                unified_prompt = construct_unified_debate_prompt(
                    question, your_ans, your_score, your_solution, others
                )
                # unified_prompt 作为下一轮的 last_user_msg
                agent_context.append(unified_prompt)

            round_idx += 1

        # save logs
        generated_description[question] = (agent_contexts, answer)

    # 记录结束时间并计算总时间和平均时间
    end_time = time.time()
    total_time = end_time - start_time
    per_sample_time = total_time / sample_count if sample_count > 0 else 0

    name = f"gsm_v3_{agents}_{rounds}_top_{sample_count}_majority_error.json"
    
    json.dump(
        generated_description,
        open(name, "w"),
    )

    print(f"\nSaved {name}\n")
    print("=" * 50)
    print("Time Statistics:")
    print(f"Total samples processed: {sample_count}")
    print(f"Total time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    print(f"Per sample time: {per_sample_time:.2f} seconds")
    print("=" * 50)
