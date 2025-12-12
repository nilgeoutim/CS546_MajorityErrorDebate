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
    unified debate prompt, give different instructions based on the score difference.
    only show the highest-scoring other agent, reduce the context length.
    """
    # find the highest-scoring other agent
    best_other = max(others, key=lambda x: x['score'])
    max_other_score = best_other['score']
    
    # determine the strategy
    if your_score >= max_other_score:
        # you are the highest score (or tied for highest)
        instruction = f"""Your score ({your_score}/10) is the highest.
KEEP your answer. Just double-check your arithmetic is correct.
If confident, output the same answer."""
        
        others_text = ""  # no need to show others
        
    elif your_score < 5 or (max_other_score - your_score) >= 2:
        # score is below 5, or more than 2 points lower than the highest score → need to learn
        instruction = f"""Your score ({your_score}/10) is lower than the best ({max_other_score}/10).
Study the highest-scoring solution below and find where your reasoning went wrong.
Adjust your approach accordingly."""
        
        others_text = f"""Highest-scoring agent's solution:
````{best_other['solution']}```
"""
    else:
        # score is close but slightly lower
        instruction = f"""Your score ({your_score}/10) is close to the best ({max_other_score}/10).
Review your solution for minor errors."""
        
        others_text = f"""Highest-scoring agent's solution: {best_other['solution']}"""

    prompt = f"""You are participating in a multi-agent debate assisted by a critic.
Your previous reasoning and answer were: ```{your_solution}```.

{instruction}

{others_text}

Problem: {question}

Provide your reasoning and end with \\boxed{{answer}}."""

    return {"role": "user", "content": prompt}



# ========== Restart Prompt (all agents' scores are low) ==========
def construct_restart_prompt(question, critic_explanation, prev_solution, prev_answer, prev_score):
    """
    when all agents' scores are low, the restart prompt used for a single agent.
    explicitly provide:
      - the previous round's reasoning of the agent (prev_solution)
      - the previous round's extracted numeric answer (prev_answer)
      - the previous round's critic score (prev_score)
      - the critic's explanation (critic_explanation)
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

    # record the start time
    start_time = time.time()

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
        round_idx = 0

        while round_idx < rounds:
            # print(f"\n========== ROUND {round_idx + 1} ==========")

            # --- store the results of each round ---
            answers_this_round = []
            scores_this_round = []
            critic_explanations_this_round = []
            solutions_this_round = []  # the complete reasoning+answer text of each agent in this round

            # --- agent inference ---
            for i, agent_context in enumerate(agent_contexts):

                # === Agent generation === (stateless: only give the last user prompt)
                # print("agent_num, prompt: ", i, last_user_msg["content"])

                completion = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=agent_context,
                    n=1,
                )
                assistant_msg = construct_assistant_message(completion)
                agent_context.append(assistant_msg)

                # save the complete reasoning text
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

            # ----- Debug output -----
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

                # 1) construct the restart prompt with explanation + the previous round's reasoning/answer for each agent
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
                # 2) reset the round number, start from 0 again for 3 rounds
                round_idx = 0
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

            round_idx += 1

        # save logs
        generated_description[question] = (agent_contexts, answer)

    # record the end time and calculate the total and average time
    end_time = time.time()
    total_time = end_time - start_time
    per_sample_time = total_time / sample_count if sample_count > 0 else 0

    name = f"gsm_confiscore_v3-5_{agents}_{rounds}_top_{sample_count}_majority_error.json"
    
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
