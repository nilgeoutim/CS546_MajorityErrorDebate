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
    """from text to extract the last number (include integer/decimal)."""
    m = re.findall(r"[-+]?\d*\.?\d+", text)
    return m[-1] if m else None


# ========== Helper: extract explanation ==========
def parse_critic_explanation(text):
    """
    old single-agent critic parsing function, not used directly in v4,
    but can be kept for future fallback usage.
    """
    m = re.search(r"Explanation\s*:\s*(.*)", text, re.DOTALL)
    if not m:
        return text.strip()
    return m.group(1).strip()


# ========== Helper: extract confidence score ==========
def parse_critic_score(text):
    """
    old single-agent critic parsing function, not used directly in v4.
    """
    m = re.search(r"Confidence\s*Score\s*:\s*([0-9]+)", text)
    if not m:
        return None
    score = int(m)
    return max(1, min(10, score))


# ======= Multi-agent Critic Prompt =======
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
    parse the JSON output of multi-agent critic.

    expected format:
    {
      "agents": [
        {"id": 0, "score": 7, "explanation": "..."},
        {"id": 1, "score": 3, "explanation": "..."},
        ...
      ]
    }

    if parsing fails, fallback:
      - all scores = 5
      - all explanations = original text
    """
    scores = [5] * num_agents
    explanations = [text.strip()] * num_agents

    try:
        # find the first '{' and the last '}', try to extract the JSON body
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
        # if parsing fails, maintain the default values
        pass

    return scores, explanations


# ========== Unified Debate Prompt (normal case: use the previous round's answer + score + reasoning) ==========

def construct_unified_debate_prompt(question, your_ans, your_score, your_solution, others):
    max_other_score = max(obj['score'] for obj in others)
    
    others_text = "\n".join([
        f"- Answer {obj['solution']}, score {obj['score']}/10" 
        for obj in others
    ])

    # give strict instructions based on the score
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


# ========== Restart Prompt (all agents' scores are low) ==========
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

    # record the start time
    start_time = time.time()

    # use tqdm to show the progress
    for data in tqdm(questions[:sample_count], desc="Processing samples", total=sample_count):
        question = data["question"]
        answer = data["answer"]

        # initialize each agent context (the starting point of the first debate)
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

            # --- store the results of each round ---
            answers_this_round = []
            solutions_this_round = []  # the complete reasoning+answer text of each agent in this round

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

            # ========== Multi-agent Critic (once-per-round scoring) ==========
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
            # # ----- Debug output -----
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

                # 1) construct the restart prompt with explanation + the previous round's reasoning/answer for each agent
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
                # 2) reset the round number, start from 0 again for 3 rounds
                continue  # go to the next round (new round)

            # ===================================================
            #      Normal Case: Construct Unified Score-Aware Debate Prompt
            # ===================================================

            for i, agent_context in enumerate(agent_contexts):
                your_ans = answers_this_round[i]
                your_score = scores_this_round[i]
                your_solution = solutions_this_round[i]

                # the answer + score + reasoning of other agents
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
                # unified_prompt as the next user message for the agent_context
                agent_context.append(unified_prompt)

        # save logs
        generated_description[question] = (agent_contexts, answer)

    # record the end time and calculate the total and average time
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
