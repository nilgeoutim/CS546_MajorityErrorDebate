"""
This script is used to generate the GSM dataset with the Confidence Score
built on basis of the majority error, using a multi-agent debate with a critic.

Version 4 (stateful):
- Agents see their full conversation history (agent_context) every round.
- Critic is called ONCE per round with all agents' reasoning & answers.
- Critic must assign a score (1-10) and explanation for EACH agent.
- Explicit rule: if two agents have different numeric answers, at most ONE of them
  can receive a high score (>= 8).
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
    旧的单-agent critic 解析函数，v4 中不再直接使用，
    但可以保留以备后续 fallback 使用。
    """
    m = re.search(r"Explanation\s*:\s*(.*)", text, re.DOTALL)
    if not m:
        return text.strip()
    return m.group(1).strip()


# ========== Helper: extract confidence score ==========
def parse_critic_score(text):
    """
    旧的单-agent critic 解析函数，v4 中不再直接使用。
    """
    m = re.search(r"Confidence\s*Score\s*:\s*([0-9]+)", text)
    if not m:
        return None
    score = int(m)
    return max(1, min(10, score))


# ======= Multi-agent Critic Prompt =======
# def construct_multi_critic_message(question, agent_solutions, agent_answers):
#     """
#     构造一次性给 critic 的 prompt，让 critic 同时看到所有 agents 的
#     reasoning + answer，并输出每个 agent 的 score 和 explanation。

#     agent_solutions: list[str]，每个 agent 本轮的完整 reasoning+answer 文本
#     agent_answers:   list[str or None]，每个 agent 提取出的 numeric answer（可能为 None）
#     """
#     agent_blocks = []
#     for idx, (sol, ans) in enumerate(zip(agent_solutions, agent_answers)):
#         ans_str = ans if ans is not None else "N/A"
#         block = (
#             f"Agent {idx}:\n"
#             f"- Extracted answer: {ans_str}\n"
#             f"- Reasoning and answer:\n```{sol}```\n"
#         )
#         agent_blocks.append(block)

#     agents_text = "\n\n".join(agent_blocks)

#     prompt = f"""
# You are a math critic. Your job is to EVALUATE and COMPARE the reasoning and final answers
# of multiple agents on the SAME math problem.

# Problem:
# {question}

# Below are the agents' solutions:

# {agents_text}

# You must assign a confidence score (1-10) and a brief explanation for EACH agent.

# IMPORTANT RULES:
# 1. A higher score means the agent's reasoning is more sound and the final answer is more likely to be correct.
# 2. If two or more agents give DIFFERENT numerical answers, at most ONE of them can receive a HIGH score (>= 8).
#    - For agents with clearly incorrect reasoning or answer, give a low score (e.g., 1-4).
#    - If all answers seem wrong, you may give all of them low scores.
# 3. If multiple agents give the SAME answer with similar, reasonable reasoning, you may give them similar scores.

# RESPONSE FORMAT (STRICT JSON):
# Respond ONLY with a single JSON object of the form:

# {{
#   "agents": [
#     {{
#       "id": 0,
#       "score": <integer 1-10>,
#       "explanation": "<brief explanation for agent 0>"
#     }},
#     {{
#       "id": 1,
#       "score": <integer 1-10>,
#       "explanation": "<brief explanation for agent 1>"
#     }},
#     ...
#   ]
# }}

# Do NOT add any extra text outside the JSON.
# """
#     return [{"role": "user", "content": prompt}]

def construct_multi_critic_message(question, agent_solutions, agent_answers):
    agent_blocks = []
    for idx, (sol, ans) in enumerate(zip(agent_solutions, agent_answers)):
        ans_str = ans if ans is not None else "N/A"
        block = f"Agent {idx} | Answer: {ans_str}\n{sol}\n"
        agent_blocks.append(block)
    agents_text = "\n---\n".join(agent_blocks)
    
    unique_answers = set(str(a) for a in agent_answers if a is not None)
    
    if len(unique_answers) > 1:
        conflict_note = f"Agents gave different answers: {unique_answers}."
    else:
        conflict_note = "All agents gave the same answer."

    prompt = f"""Problem: {question}

{agents_text}

{conflict_note}

For each agent, verify step-by-step:
1. Is the equation setup correct for this problem?
2. Is each calculation step valid?
3. Does the final answer follow from the reasoning?

Scoring rules:
- 8-10: Sound logic AND likely correct answer
- 4-7: Partial errors but reasonable attempt
- 1-3: Flawed logic or wrong setup

STRICT RULES:
- If answers differ, at most ONE can score ≥8 (the most likely correct one)
- If ALL agents have flawed reasoning, ALL should score ≤5
- Do not give high scores just because format looks clean

JSON only:
{{"agents":[{{"id":0,"score":<int>,"flaw":"<specific error or none>"}},{{"id":1,"score":<int>,"flaw":"<specific error or none>"}},{{"id":2,"score":<int>,"flaw":"<specific error or none>"}}]}}"""

    return [{"role": "user", "content": prompt}]

def parse_multi_critic_output(text, num_agents):
    """
    解析 multi-agent critic 的 JSON 输出。

    期望格式:
    {
      "agents": [
        {"id": 0, "score": 7, "explanation": "..."},
        {"id": 1, "score": 3, "explanation": "..."},
        ...
      ]
    }

    如果解析失败，则 fallback:
      - 所有 score = 5
      - 所有 explanation = 原始 text
    """
    scores = [5] * num_agents
    explanations = [text.strip()] * num_agents

    try:
        # 找到第一个 '{' 和最后一个 '}'，尽量截出 JSON 主体
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            json_str = text[first : last + 1]
        else:
            json_str = text

        data = json.loads(json_str)

        if "agents" in data and isinstance(data["agents"], list):
            for item in data["agents"]:
                try:
                    idx = int(item.get("id", -1))
                    if 0 <= idx < num_agents:
                        sc = int(item.get("score", 5))
                        sc = max(1, min(10, sc))
                        scores[idx] = sc
                        expl = str(item.get("explanation", "")).strip()
                        explanations[idx] = expl if expl else explanations[idx]
                except Exception:
                    continue
    except Exception:
        # 解析失败就维持默认值
        pass

    return scores, explanations


# ========== Unified Debate Prompt（正常情况：使用上一轮的 answer + score + reasoning） ==========
# def construct_unified_debate_prompt(question, your_ans, your_score, your_solution, others):
#     """
#     统一的 debate prompt，使用上一轮的 answer + score + reasoning。
#     """

#     others_text = ""
#     for j, obj in enumerate(others):
#         others_text += (
#             f"One agent's answer:  ```{obj['solution']}```, its score is {obj['score']}/10\n"
#         )

#     prompt = f"""
# You are participating in a multi-agent debate assisted by a critic.

# Your previous reasoning and answer were:
# ```{your_solution}```, your score is {your_score}/10

# Here are the previous round's answers and confidence scores from other agents:

# {others_text}
# Based on these scores:

# - If your score is significantly higher than others, KEEP and DEFEND your reasoning and answer.
# - If your score is significantly lower, STUDY the highest-scoring agent’s answer and adjust your reasoning accordingly.

# Considering the above information, please provide your reasoning and answer to the original problem:
# {question}

# Your final answer must end with \\boxed{{answer}}.
# """
#     return {"role": "user", "content": prompt}


def construct_unified_debate_prompt(question, your_ans, your_score, your_solution, others):
    max_other_score = max(obj['score'] for obj in others)
    
    others_text = "\n".join([
        f"- Answer {obj['solution']}, score {obj['score']}/10" 
        for obj in others
    ])

    # 根据分数给出强硬指令
    if your_score >= 9:
        instruction = f"""Your score is {your_score}/10 (HIGH). 
DO NOT change your answer. Only verify your arithmetic is correct.
If confident, output the same answer again."""
    elif your_score >= max_other_score:
        instruction = f"""Your score {your_score}/10 is highest. 
Keep your approach, just double-check calculations."""
    else:
        instruction = f"""Your score {your_score}/10 is lower than others.
Find your error and learn from higher-scoring agents."""

    prompt = f""" Your answer: {your_solution} (score {your_score}/10)
Others:
{others_text}

{instruction}

Original Problem: {question}. Solve again. End with \\boxed{{answer}}."""

    return {"role": "user", "content": prompt}


# ========== Restart Prompt（所有 agent 分数都低） ==========
# def construct_restart_prompt(question, critic_explanation, prev_solution, prev_answer, prev_score):
#     """
#     当所有 agent 的 score 都很低时，对单个 agent 使用的 restart prompt。
#     显式提供该 agent 的上一轮 reasoning / answer / score / explanation。
#     """
#     prev_ans_str = prev_answer if prev_answer is not None else "N/A"

#     return {
#         "role": "user",
#         "content": (
#             "The critic believes your previous reasoning was not correct.\n\n"
#             "Your previous reasoning and answer were:\n"
#             f"```{prev_solution}```\n"
#             f"The critic gave it a confidence score of {prev_score}/10.\n\n"
#             f"Reason given by the critic: {critic_explanation}\n\n"
#             "Please restart your reasoning from scratch and independently solve the problem:\n"
#             f"{question}\n\n"
#             "Do not simply repeat your previous solution; carefully re-derive the answer step by step.\n"
#             "End with \\boxed{{answer}}."
#         ),
#     }
def construct_restart_prompt(question, critic_explanation, prev_solution, prev_answer, prev_score):
    prompt = f"""Your solution was incorrect (score {prev_score}/10).

Problem: {question}

Critic feedback: {critic_explanation}

Solve from scratch:
1. Re-read the problem carefully
2. Set up equations step by step
3. Check arithmetic

Do NOT repeat previous errors. End with \\boxed{{answer}}."""

    return {"role": "user", "content": prompt}


# ========== Assistant Message ==========
def construct_assistant_message(completion):
    content = completion.choices[0].message.content
    return {"role": "assistant", "content": content}


# ========== Read JSONL ==========
def read_jsonl(path: str):
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]


# ===============================================================
#                       MAIN (v4, stateful)
# ===============================================================

if __name__ == "__main__":
    agents = 5
    rounds = 4
    sample_count = 50
    random.seed(0)

    HIGH_THRESHOLD = 5   # high confidence for early stop
    LOW_THRESHOLD = 7    # low confidence triggers restart

    generated_description = {}

    questions = read_jsonl("gsm_majority_error.jsonl")
    # random.shuffle(questions)

    client = openai.OpenAI()

    # 记录开始时间
    start_time = time.time()

    # 使用 tqdm 显示进度
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

        for round_idx in range(rounds):
            # print(f"\n========== ROUND {round_idx + 1} ==========")

            # --- 每轮存储结果 ---
            answers_this_round = []
            solutions_this_round = []  # 每个 agent 本轮的完整 reasoning+answer 文本

            # --- agent inference ---
            for i, agent_context in enumerate(agent_contexts):

                # print("agent number", i, "agent context:\n", agent_context[-1]["content"])
                # === Agent generation ===
                completion = client.chat.completions.create(
                    model="gpt-3.5-turbo-0125",
                    messages=agent_context,
                    n=1,
                )
                # print("agent number", i, "agent raw output:\n", completion.choices[0].message.content)
                assistant_msg = construct_assistant_message(completion)
                agent_context.append(assistant_msg)

                # 保存完整 reasoning 文本
                solutions_this_round.append(assistant_msg["content"])

                # Extract numeric answer
                ans_number = extract_number(assistant_msg["content"])
                answers_this_round.append(ans_number)

            # ========== Multi-agent Critic (一次性评分) ==========
            critic_messages = construct_multi_critic_message(
                question,
                solutions_this_round,
                answers_this_round,
            )
            critic_completion = client.chat.completions.create(
                model="gpt-3.5-turbo-0125",
                messages=critic_messages,
                n=1,
            )
            critic_content = critic_completion.choices[0].message.content
            # print("multi-critic raw output:\n", critic_content)

            scores_this_round, critic_explanations_this_round = parse_multi_critic_output(
                critic_content, agents
            )
            # # ----- Debug 输出 -----
            # print(f"GT: {extract_number(answer)}")
            # for i in range(agents):
            #     print(f"Agent {i}: answer={answers_this_round[i]}, score={scores_this_round[i]}")
            # print("-----------------------------------")

            #           Early Stopping Conditions:
            #           Condition A: High-consensus early stop
            # if len(set(answers_this_round)) == 1 and all(
            #     s >= HIGH_THRESHOLD for s in scores_this_round
            # ):
            #     break

            # ==== Condition B: All agents low-confidence ====
            if all(s < LOW_THRESHOLD for s in scores_this_round):

                # 1) 对每个 agent 构造带 explanation + 上一轮 reasoning/answer 的 restart prompt
                new_agent_contexts = []
                for i in range(agents):
                    expl = critic_explanations_this_round[i]
                    prev_sol = solutions_this_round[i]
                    prev_ans = answers_this_round[i]
                    prev_score = scores_this_round[i]
                    restart_prompt = construct_restart_prompt(
                        question,
                        expl,
                        prev_sol,
                        prev_ans,
                        prev_score,
                    )

                agent_contexts[i].append(restart_prompt)
                # 2) 重置轮数，从 0 再来 3 轮
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
                # unified_prompt 作为该 agent_context 的下一条 user 消息
                agent_context.append(unified_prompt)

        # save logs
        generated_description[question] = (agent_contexts, answer)

    # 记录结束时间并计算总时间和平均时间
    end_time = time.time()
    total_time = end_time - start_time
    per_sample_time = total_time / sample_count if sample_count > 0 else 0

    name = f"gsm_v4_stateful_{agents}_{rounds}_top_{sample_count}_majority_error.json"
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
