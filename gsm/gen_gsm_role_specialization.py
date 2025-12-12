"""
This script is used to generate the GSM dataset with the Confidence Score (v5).
Features:
- Multi-agent debate with Personas (Logician, Programmer, Skeptic).
- Stateful conversation history.
- Multi-agent Critic (Confidence Score).
- Debate / Restart logic based on scores.
"""

import openai
import json
import numpy as np
import random
import re
import time
import os
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =====================================================================================
#  SECTION 1: Helper Functions (Regex & Parsing)
# =====================================================================================

def extract_number(text):
    """from text to extract the last number (include integer/decimal)."""
    m = re.findall(r"[-+]?\d*\.?\d+", text)
    return m[-1] if m else None

# =====================================================================================
#  SECTION 2: Persona & Prompt Construction (V5 Logic)
# =====================================================================================

def construct_actor_prompt(question: str, persona: str = "default") -> list:
    """Constructs the Round 0 Actor Prompt with Persona Support."""
    
    if persona == "logician":
        return [
            {"role": "system", "content": "You are a logical thinker. Solve this problem step-by-step. Break down complex logic into simple, sequential steps."},
            {"role": "user", "content": f"Can you solve the following math problem? {question}\n\nExplain your reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step."}
        ]
    elif persona == "programmer":
        return [
            {"role": "system", "content": "You are a Python expert. Write a Python script to solve this math problem. Then, deduce the final answer from your code logic and output it."},
            {"role": "user", "content": f"Problem: {question}\n\n1. Write a Python script to solve the problem.\n2. Based on the logic in your code, provide the final numerical answer in the form \\boxed{{answer}} at the very end."}
        ]
    elif persona == "skeptic":
        return [
            {"role": "system", "content": "You are a critical reviewer. Use 'Contrastive Chain-of-Thought' reasoning."},
            {"role": "user", "content": f"Problem: {question}\n\nTask:\n1. First, describe 2 plausible but INCORRECT ways to approach this problem and explain why they are wrong (Negative Constraints).\n2. Then, solve it correctly avoiding these traps.\n3. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response."}
        ]
    else: # Default
        return [
            {"role": "system", "content": "You are a helpful assistant that solves math problems. Think step by step."},
            {"role": "user", "content": f"Can you solve the following math problem? {question}\n\nExplain your reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step."}
        ]

def construct_multi_critic_message(question, agent_solutions, agent_answers, agent_personas):
    agent_blocks = []
    for idx, (sol, ans, persona) in enumerate(zip(agent_solutions, agent_answers, agent_personas)):
        ans_str = ans if ans is not None else "N/A"
        # Just show "Agent {idx}" to the critic, or maybe "Agent {idx} ({persona})" if specific evaluation is needed.
        # Critic doesn't strictly need to know the persona, but it might help context.
        block = f"Agent {idx} (Role: {persona}) | Answer: {ans_str}\n{sol}\n"
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
- If answers differ, at most ONE can score >= 8 (the most likely correct one)
- If ALL agents have flawed reasoning, ALL should score <= 5
- Do not give high scores just because format looks clean

JSON only:
{{"agents":[{{"id":0,"score":<int>,"flaw":"<specific error or none>"}},{{"id":1,"score":<int>,"flaw":"<specific error or none>"}},{{"id":2,"score":<int>,"flaw":"<specific error or none>"}}]}}"""

    return [{"role": "user", "content": prompt}]

def parse_multi_critic_output(text, num_agents):
    scores = [5] * num_agents
    explanations = [text.strip()] * num_agents

    try:
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
                        expl = str(item.get("flaw", item.get("explanation", ""))).strip()
                        explanations[idx] = expl if expl else explanations[idx]
                except Exception:
                    continue
    except Exception:
        pass

    return scores, explanations

def construct_unified_debate_prompt(question, your_ans, your_score, your_solution, others, persona):
    max_other_score = max(obj['score'] for obj in others) if others else 0
    
    others_text = "\n".join([
        f"- Answer {obj['solution']}, score {obj['score']}/10" 
        for obj in others
    ])

    if your_score >= 9:
        instruction = f"Your score is {your_score}/10 (HIGH). DO NOT change your answer. Only verify your arithmetic is correct. If confident, output the same answer again."
    elif your_score >= max_other_score:
        instruction = f"Your score {your_score}/10 is highest. Keep your approach, just double-check calculations."
    else:
        instruction = f"Your score {your_score}/10 is lower than others. Find your error and learn from higher-scoring agents."

    # Remind persona if necessary, especially for Programmer
    persona_instruction = ""
    if persona == "programmer":
        persona_instruction = "Remember to provide updated code or logic if needed."
    elif persona == "skeptic":
        persona_instruction = "Maintain your critical eye. Avoid previous traps."

    prompt = f"""Your answer: {your_solution} (score {your_score}/10)
Others:
{others_text}

{instruction}
{persona_instruction}

Original Problem: {question}. Solve again. End with \\boxed{{answer}}."""

    return {"role": "user", "content": prompt}

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

def construct_assistant_message(completion):
    content = completion.choices[0].message.content
    return {"role": "assistant", "content": content}

def read_jsonl(path: str):
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]

# =====================================================================================
#  SECTION 3: Main Execution (V5)
# =====================================================================================

if __name__ == "__main__":
    agents = 3 # Use 3 agents to match the 3 personas
    rounds = 4
    sample_count = 50
    random.seed(0)

    HIGH_THRESHOLD = 9   # Higher threshold for completion
    LOW_THRESHOLD = 4    # Threshold for restart

    generated_description = {}
    
    data_file = "gsm/gsm_majority_error.jsonl"
    output_file = "gsm/gsm_v5_confiscore_roles.json"

    questions = read_jsonl(data_file)
    client = openai.OpenAI()

    print(f"Starting V5 Generation (Confiscore + Roles)")
    print(f"Output: {output_file}")

    start_time = time.time()

    for data in tqdm(questions[:sample_count], desc="Processing samples", total=sample_count):
        question = data["question"]
        answer = data["answer"]

        # Assign personas
        personas = ["logician", "programmer", "skeptic"]
        if agents > 3:
             # Cycle if more agents
             full_personas = [personas[i % 3] for i in range(agents)]
        else:
             full_personas = personas[:agents]

        # Initialize contexts with Persona Prompts
        agent_contexts = []
        for i in range(agents):
            init_msgs = construct_actor_prompt(question, full_personas[i])
            agent_contexts.append(init_msgs)

        for round_idx in range(rounds):
            answers_this_round = []
            solutions_this_round = []

            # --- Agent Inference ---
            for i, agent_context in enumerate(agent_contexts):
                completion = client.chat.completions.create(
                    model="gpt-3.5-turbo-0125",
                    messages=agent_context,
                    n=1,
                )
                assistant_msg = construct_assistant_message(completion)
                agent_context.append(assistant_msg)
                
                solutions_this_round.append(assistant_msg["content"])
                
                # Extract numeric answer
                # For programmer, extract from boxed preferably, or last number
                ans_str = assistant_msg["content"]
                
                # Try finding boxed first (more reliable for all agents now)
                boxed_match = re.search(r"\\boxed\{(.*?)\}", ans_str)
                if boxed_match:
                    ans_number = extract_number(boxed_match.group(1))
                else:
                    ans_number = extract_number(ans_str)
                
                answers_this_round.append(ans_number)

            # --- Multi-agent Critic ---
            critic_messages = construct_multi_critic_message(
                question,
                solutions_this_round,
                answers_this_round,
                full_personas
            )
            critic_completion = client.chat.completions.create(
                model="gpt-3.5-turbo-0125",
                messages=critic_messages,
                n=1,
            )
            critic_content = critic_completion.choices[0].message.content
            scores_this_round, critic_explanations_this_round = parse_multi_critic_output(critic_content, agents)

            # --- Logic Flow ---
            
            # Condition A: Early Stop (Consensus + High Score)
            # Check if majority agree and have high scores? 
            # Or just check if ALL agree and have decent scores?
            # V4 used: set(answers) == 1 and all(scores >= HIGH)
            valid_answers = [a for a in answers_this_round if a is not None]
            if len(valid_answers) == agents and len(set(valid_answers)) == 1 and all(s >= 8 for s in scores_this_round):
                # We can stop early if everyone agrees and score is high
                break

            # Condition B: Restart (All Low Confidence)
            if all(s < LOW_THRESHOLD for s in scores_this_round):
                for i in range(agents):
                    expl = critic_explanations_this_round[i]
                    prev_sol = solutions_this_round[i]
                    prev_ans = answers_this_round[i]
                    prev_score = scores_this_round[i]
                    restart_msg = construct_restart_prompt(question, expl, prev_sol, prev_ans, prev_score)
                    agent_contexts[i].append(restart_msg)
                continue # Go to next round

            # Condition C: Debate (Normal)
            for i, agent_context in enumerate(agent_contexts):
                your_ans = answers_this_round[i]
                your_score = scores_this_round[i]
                your_solution = solutions_this_round[i]

                others = []
                for j in range(agents):
                    if j == i: continue
                    others.append({
                        "ans": answers_this_round[j],
                        "score": scores_this_round[j],
                        "solution": solutions_this_round[j],
                    })

                unified_prompt = construct_unified_debate_prompt(
                    question, your_ans, your_score, your_solution, others, full_personas[i]
                )
                agent_context.append(unified_prompt)

        generated_description[question] = (agent_contexts, answer)

    end_time = time.time()
    total_time = end_time - start_time
    
    with open(output_file, "w") as f:
        json.dump(generated_description, f)

    print(f"\nSaved {output_file}\n")
    print("=" * 50)
    print(f"Total time: {total_time:.2f} seconds")
    print("=" * 50)
