import transformers
import torch
import json
import numpy as np
import random
import re
import time
from tqdm import tqdm

# --- Helper Functions from original files ---

def read_jsonl(path: str):
    """Reads a .jsonl file and returns a list of dictionaries."""
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]

def parse_critic_output(text: str):
    """
    Parses the JSON output from the critic LLM.
    Handles cases where the LLM might add extra text around the JSON.
    """
    try:
        # Find the first '{' and the last '}'
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            data = json.loads(json_str)
            # Ensure keys exist
            return {
                'logic_score': data.get('logic_score', 0),
                'computation_score': data.get('computation_score', 0),
                'critique': data.get('critique', 'Parsing error or missing critique.')
            }
        else:
            print(f"Warning: No JSON object found in critic output: {text}")
            return {'logic_score': 0, 'computation_score': 0, 'critique': 'Failed to find JSON object.'}
    except json.JSONDecodeError:
        print(f"Warning: Failed to decode JSON from critic: {text}")
        return {'logic_score': 0, 'computation_score': 0, 'critique': 'JSONDecodeError.'}

# --- New Prompt Construction Functions ---

def construct_actor_prompt(question: str):
    """
    Creates the initial prompt for the Actor agent to solve the problem.
    """
    content = f"""Can you solve the following math problem? {question}
Explain your reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step."""
    return [{"role": "user", "content": content}]

def construct_critic_prompt(question: str, solution: str):
    """
    Creates the prompt for the Critic agent to evaluate a given solution.
    It requests scores for Logic (S_Logic) and Computation (S_Comp) as JSON.
    """
    content = f"""You are a Critic agent. Your task is to evaluate a given solution to a math problem based on its logic and computation.
The problem is:
"{question}"

The proposed solution is:
```
{solution}
```

Please provide your evaluation in a single JSON object with three keys:
1.  `logic_score`: An integer score from 1 (poor) to 10 (perfect) rating the logical coherence and soundness of the reasoning steps.
2.  `computation_score`: An integer score from 1 (poor) to 10 (perfect) rating the accuracy of numerical calculations.
3.  `critique`: A brief, one-sentence explanation for your scores.

Your response MUST be only the JSON object.
"""
    return [{"role": "user", "content": content}]

def format_other_solutions_scores(other_solutions_scores: list) -> str:
    """Helper to format other agents' data for the debate prompt."""
    formatted_string = ""
    for i, item in enumerate(other_solutions_scores):
        solution = item['solution']
        score = item['score']
        formatted_string += f"\n--- Agent {i+1} Solution ---\n"
        formatted_string += f"Logic Score: {score['logic_score']}/10\n"
        formatted_string += f"Computation Score: {score['computation_score']}/10\n"
        formatted_string += f"Critique: {score['critique']}\n"
        formatted_string += f"Solution:\n```\n{solution}\n```\n"
    return formatted_string

def construct_debate_prompt(question: str, my_solution: str, my_score: dict, other_solutions_scores: list):
    """
    Creates the prompt for the Actor agent's second round (the debate).
    It implements the "adaptive threshold" by instructing the agent to compare scores.
    """
    
    other_agents_info = format_other_solutions_scores(other_solutions_scores)

    content = f"""You are a debater in a multi-agent debate to solve a math problem.
The original problem is:
"{question}"

--- Your Previous Solution ---
Your solution was:
```
{my_solution}
```
Your solution was evaluated by a Critic with the following scores:
-   Logic Score: {my_score['logic_score']}/10
-   Computation Score: {my_score['computation_score']}/10
-   Critique: {my_score['critique']}

--- Other Agents' Solutions and Scores ---
{other_agents_info}

--- Your Task ---
Review all solutions and their scores.
Your goal is to find the *most accurate* answer.
-   If you believe your original solution is correct despite low scores or other opinions, defend it and restate your answer.
-   If you find another agent's solution is demonstrably better (based on its high logic/computation scores and your own re-evaluation), you should adopt its reasoning and answer.

Provide your final, updated reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step.
"""
    return [{"role": "user", "content": content}]

# --- Main Execution ---

if __name__ == "__main__":
    agents = 3  # 3 Actor agents
    # A 2-round debate: Round 1 = initial solve, Round 2 = debate
    rounds = 2 
    random.seed(0)

    # --- Load Llama Model ---
    # This is the same setup as your gen_gsm.py
    model_id = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    print(f"Loading model: {model_id}...")
    pipeline = transformers.pipeline(
        "text-generation",
        model=model_id,
        model_kwargs={"torch_dtype": torch.bfloat16},
        device_map="auto",
    )
    # Set a terminator to stop the model from rambling
    # Note: Adjust terminators based on the specific Llama model's prompting guide
    terminators = [
        pipeline.tokenizer.eos_token_id,
        pipeline.tokenizer.convert_tokens_to_ids("<|eot_id|>")
    ]
    print("Model loaded.")

    results = {}
    questions = read_jsonl("gsm_test.jsonl") 
    random.shuffle(questions)

    # We will process 100 questions as in the original script
    # can be use 100 questions for smoke test, and then use the full set for final run
    # for data in tqdm(questions[:100], desc="Processing Questions"):
    for data in tqdm(questions, desc="Processing Questions"):
        question = data['question']
        answer = data['answer']

        agent_solutions = [None] * agents
        agent_scores = [None] * agents
        
        # --- ROUND 1: Initial Solve (Actor) + Critique (Critic) ---
        
        # 1. Actor Phase: All agents generate initial solutions
        for i in range(agents):
            actor_prompt = construct_actor_prompt(question)
            
            outputs = pipeline(
                actor_prompt,
                max_new_tokens=1024, # Allow space for reasoning
                eos_token_id=terminators,
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
            )
            solution_text = outputs[0]["generated_text"][-1]['content']
            agent_solutions[i] = solution_text

        # 2. Critic Phase: All solutions are scored
        for i in range(agents):
            critic_prompt = construct_critic_prompt(question, agent_solutions[i])
            
            outputs = pipeline(
                critic_prompt,
                max_new_tokens=256, # JSON output is small
                eos_token_id=terminators,
                do_sample=False, # We want deterministic JSON output
            )
            critique_text = outputs[0]["generated_text"][-1]['content']
            agent_scores[i] = parse_critic_output(critique_text)

        # Store Round 1 results
        round_1_data = [{"solution": s, "score": c} for s, c in zip(agent_solutions, agent_scores)]

        # --- ROUND 2: Debate (Actor) + Final Critique (Critic) ---
        # This loop implements the "rounds > 1" logic
        
        final_solutions = [None] * agents
        final_scores = [None] * agents

        # 3. Debate Phase: All agents re-evaluate based on others' scores
        for i in range(agents):
            my_solution = agent_solutions[i]
            my_score = agent_scores[i]
            
            other_solutions_scores = []
            for j in range(agents):
                if i != j:
                    other_solutions_scores.append({"solution": agent_solutions[j], "score": agent_scores[j]})
            
            debate_prompt = construct_debate_prompt(question, my_solution, my_score, other_solutions_scores)

            outputs = pipeline(
                debate_prompt,
                max_new_tokens=1024,
                eos_token_id=terminators,
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
            )
            solution_text = outputs[0]["generated_text"][-1]['content']
            final_solutions[i] = solution_text

        # 4. Final Critic Phase: Score the final answers
        for i in range(agents):
            critic_prompt = construct_critic_prompt(question, final_solutions[i])
            
            outputs = pipeline(
                critic_prompt,
                max_new_tokens=256,
                eos_token_id=terminators,
                do_sample=False,
            )
            critique_text = outputs[0]["generated_text"][-1]['content']
            final_scores[i] = parse_critic_output(critique_text)

        # --- Save results for this question ---
        results[question] = {
            "ground_truth": answer,
            "round_1_results": round_1_data,
            "final_round_results": [{"solution": s, "score": c} for s, c in zip(final_solutions, final_scores)]
        }

        # Save checkpoint after each question
        json.dump(results, open(f"gsm_critic_actor_{agents}_{rounds}.json", "w"), indent=2)

    print("Experiment finished.")
    print(f"Results saved to gsm_critic_actor_{agents}_{rounds}.json")
