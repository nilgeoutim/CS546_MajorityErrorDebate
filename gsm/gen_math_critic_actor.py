import transformers
import torch
import json
import numpy as np
import random
from tqdm import tqdm
import re
import time

# =====================================================================================
#  SECTION 1: Prompt Construction (v2-Final-Fix)
# =====================================================================================

def construct_actor_prompt(question: str) -> list:
    """Constructs the Round 1 Actor Prompt."""
    return [
        {"role": "system", "content": "You are a helpful assistant that solves math problems. Think step by step."},
        {"role": "user", "content": f"Can you solve the following math problem? {question}\n\nExplain your reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step."}
    ]

def construct_critic_prompt(question: str, solution: str) -> list:
    """
    (v2-Final-Fix) Constructs the 'Critic' prompt.
    1. Requires 'verification_step' CoT.
    2. Requires 0.5-step floating point scores.
    3. (NEW) Asks for JSON in a markdown code block for stability.
    """
    return [
        {"role": "system", "content": "You are a Critic agent. Your task is to evaluate a given solution to a math problem based on its logical coherence and computation accuracy. Provide your evaluation in JSON format."},
        {"role": "user", "content": f"""Here is the math problem:
---
{question}
---

Here is the proposed solution:
---
{solution}
---

Please evaluate this solution. You MUST provide your evaluation in a single JSON object inside a markdown code block (```json ... ```) with FOUR keys:
1.  `verification_step` (str): First, briefly verify a key calculation or logic step. (e.g., "Verified step 2: 30 / 60 = 0.5. This is correct.")
2.  `logic_score` (float, 1.0-10.0): Based on your verification, rate the logical coherence. Use 0.5 steps (e.g., 8.0, 8.5, 9.0).
3.  `computation_score` (float, 1.0-10.0): Based on your verification, rate the computation accuracy. Use 0.5 steps.
4.  `critique` (str, 1-2 sentences): A brief explanation for your scores.

Your response MUST be only the markdown code block containing the JSON object.
"""}
    ]

def construct_debate_prompt(question: str, self_analysis: dict, other_analyses: list) -> list:
    """ 
    (v2-Final-Fix) Constructs the Round 2 'Debater' prompt.
    Includes multi-dimensional (Logic OR Comp) quantified threshold.
    """
    
    # Format the current agent's previous analysis
    self_solution = self_analysis['solution']
    self_logic = self_analysis['score']['logic_score']
    self_comp = self_analysis['score']['computation_score']
    self_critique = self_analysis['score']['critique']
    self_prompt_part = f"""
--- YOUR PREVIOUS ANALYSIS (Round 1) ---
Your Solution:
```
{self_solution}
```
Your Scores:
- Logic: {self_logic:.1f}/10.0
- Computation: {self_comp:.1f}/10.0
- Critique: {self_critique}
"""

    # Format other agents' analyses
    other_prompt_part = "\n--- OTHER AGENTS' ANALYSES (Round 1) ---\n"
    if not other_analyses:
        other_prompt_part += "No other agents provided analysis in this round.\n"
    else:
        for i, analysis in enumerate(other_analyses):
            other_solution = analysis['solution']
            other_logic = analysis['score']['logic_score']
            other_comp = analysis['score']['computation_score']
            other_critique = analysis['score']['critique']
            other_prompt_part += f"""
Agent {i+1}'s Solution:
```
{other_solution}
```
Agent {i+1}'s Scores:
- Logic: {other_logic:.1f}/10.0
- Computation: {other_comp:.1f}/10.0
- Critique: {other_critique}
---
"""

    # Multi-dimensional quantified threshold
    system_prompt = "You are a debater in a multi-agent debate. Your goal is to find the *most accurate* answer to the math problem by re-evaluating your own solution against the solutions and critiques from other agents."
    user_prompt = f"""
The original math problem is:
{question}

You and other agents have all proposed solutions and received critiques. Now, you must re-evaluate everything to provide a final, definitive answer.

{self_prompt_part}
{other_prompt_part}

--- YOUR TASK (Round 2) ---
Carefully re-evaluate your own solution and the other agents' solutions, paying close attention to the logic, computation, and critiques.

1.  **(Multi-Dimensional Threshold)** Only adopt another agent's solution if it is *demonstrably* better. This means:
    (its `logic_score` is **at least 2.0 points higher** than yours) 
    OR 
    (its `computation_score` is **at least 3.0 points higher** than yours)
    AND your own re-evaluation confirms it is correct.
2.  **(Minority Defense)** Conversely, if you are confident your solution is correct and other agents are wrong, *do not* conform, even if scores are close. Defend your solution and explain *why* their logic is flawed.
3.  Provide your final, step-by-step reasoning.
4.  Conclude with your final answer in the form \\boxed{{answer}}.

Let's think step by step again.
"""
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

# =====================================================================================
#  SECTION 2: Helper Functions
# =====================================================================================

def read_jsonl(path: str) -> list:
    """Reads a JSONL file."""
    with open(path, 'r', encoding='utf-8') as fh:
        return [json.loads(line) for line in fh.readlines() if line]

def _safe_parse_float(value: any, default: float = 0.0) -> float:
    """Robustly convert a value to float, handling strings, int, etc."""
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    return default

def parse_critic_output(text: str) -> dict:
    """
    (v2-Final-Fix) Safely extract the 4-key JSON and parse floats.
    Now searches for ```json code blocks first.
    """
    default_score = {
        "verification_step": "Error: Could not parse output.",
        "logic_score": 0.0, 
        "computation_score": 0.0, 
        "critique": "Error parsing output."
    }
    try:
        # (NEW) First, try to find a markdown JSON code block
        match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        
        if match:
            json_str = match.group(1)
        else:
            # Fallback: find the first and last curly brace
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                json_str = match.group(0)
            else:
                # If no JSON block or curly braces are found
                print(f"\n[Warning] No JSON found in critic output.\nText was: {text}\n")
                return default_score

        # Now, try to load the found json_str
        data = json.loads(json_str)
        
        if 'logic_score' in data and 'computation_score' in data and 'critique' in data and 'verification_step' in data:
            return {
                "verification_step": str(data.get("verification_step", "")),
                "logic_score": _safe_parse_float(data.get("logic_score")),
                "computation_score": _safe_parse_float(data.get("computation_score")),
                "critique": str(data.get("critique", ""))
            }
        else:
            print(f"\n[Warning] JSON missing required keys.\nText was: {text}\n")
            return default_score
            
    except Exception as e:
        print(f"\n[Warning] Failed to parse critic JSON: {e}\nText was: {text}\n")
        return default_score

def call_pipeline(pipeline, messages, gen_config):
    """
    (v2-Final-Fix) Helper function to call the generation pipeline.
    Now takes a gen_config dict for all parameters.
    """
    terminators = [
        pipeline.tokenizer.eos_token_id, 
        pipeline.tokenizer.convert_tokens_to_ids("<|end_of_text|>")
    ]
    
    outputs = pipeline(
        messages,
        max_new_tokens=gen_config['max_tokens'],
        eos_token_id=terminators,
        do_sample=gen_config['do_sample'],
        temperature=gen_config['temp'],
        top_p=gen_config['top_p'],
    )
    
    generated_text = outputs[0]["generated_text"][-1]['content']
    return generated_text

# =====================================================================================
#  SECTION 3: Main Execution
# =====================================================================================

if __name__ == "__main__":
    # --- 1. All Configuration Parameters (Refactored) ---
    config = {
        "agents": 3,
        "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
        "data_file": "gsm_test.jsonl",
        "output_file": f"gsm_critic_actor_3_2_v2_final_fix.json", # v2-Final-Fix output
        "questions_to_process": 100 # Set to full list length if needed
    }
    
    # Generation config for Actors (diverse, creative)
    actor_gen_config = {
        "max_tokens": 1024, # Your 1024 limit
        "do_sample": False,
        "temp": None,
        "top_p": 0.9
    }
    
    # Generation config for Critics (deterministic, structured)
    critic_gen_config = {
        "max_tokens": 256,
        "do_sample": False,
        "temp": None,
        "top_p": None
    }
    
    print("="*50)
    print(f"Starting Critic-Actor (v2-Final-Fix) Experiment")
    print(f"Model: {config['model_id']}")
    print(f"Agent Count: {config['agents']}")
    print(f"Output File: {config['output_file']}")
    print("="*50)

    # --- 2. Load Model ---
    print("Loading Llama 3.1, please wait...")
    pipeline = transformers.pipeline(
        "text-generation",
        model=config['model_id'],
        model_kwargs={"torch_dtype": torch.bfloat16},
        device_map="auto",
    )
    print("✅ Llama 3.1 Loaded.")

    # --- 3. Load Data ---
    print(f"Loading data from {config['data_file']}...")
    try:
        questions = read_jsonl(config['data_file'])
        random.seed(0)
        random.shuffle(questions)
        questions_subset = questions[:config['questions_to_process']]
        print(f"✅ Data Loaded. Processing {len(questions_subset)} problems.")
    except FileNotFoundError:
        print(f"❌ Error: Data file not found at '{config['data_file']}'.")
        print("Please ensure 'gsm_test.jsonl' is in the same directory.")
        exit()

    # --- 4. Run Experiment ---
    results = {}
    
    for data in tqdm(questions_subset, desc="Processing Questions"):
        question = data['question']
        ground_truth = data['answer']
        
        round_1_results = []
        
        # --- Stage 1: Initial Actor Solutions ---
        actor_prompts = [construct_actor_prompt(question) for _ in range(config['agents'])]
        actor_solutions = []
        for i in range(config['agents']):
            solution_text = call_pipeline(
                pipeline, actor_prompts[i], actor_gen_config
            )
            actor_solutions.append(solution_text)
            time.sleep(0.1) 

        # --- Stage 2: Initial Critic Scores ---
        critic_prompts = [construct_critic_prompt(question, sol) for sol in actor_solutions]
        critic_scores = []
        for i in range(config['agents']):
            score_text = call_pipeline(
                pipeline, critic_prompts[i], critic_gen_config
            )
            critic_scores.append(parse_critic_output(score_text))
            time.sleep(0.1)

        # Collate Round 1 results
        for sol, score in zip(actor_solutions, critic_scores):
            round_1_results.append({"solution": sol, "score": score})

        # --- Stage 3: Actor Debate (v2-Final-Fix) ---
        debate_prompts = []
        for i in range(config['agents']):
            self_analysis = round_1_results[i]
            other_analyses = round_1_results[:i] + round_1_results[i+1:]
            debate_prompts.append(construct_debate_prompt(question, self_analysis, other_analyses))

        final_solutions = []
        for i in range(config['agents']):
            final_solution_text = call_pipeline(
                pipeline, debate_prompts[i], actor_gen_config # Use actor config
            )
            final_solutions.append(final_solution_text)
            time.sleep(0.1)

        # --- Stage 4: Final Critic Scores ---
        final_critic_prompts = [construct_critic_prompt(question, sol) for sol in final_solutions]
        final_critic_scores = []
        for i in range(config['agents']):
            final_score_text = call_pipeline(
                pipeline, final_critic_prompts[i], critic_gen_config
            )
            final_critic_scores.append(parse_critic_output(final_score_text))
            time.sleep(0.1)

        # Collate Final Round results
        final_round_results = []
        for sol, score in zip(final_solutions, final_critic_scores):
            final_round_results.append({"solution": sol, "score": score})
            
        # --- 5. Save result for this question ---
        results[question] = {
            "ground_truth": ground_truth,
            "round_1_results": round_1_results,
            "final_round_results": final_round_results
        }

    # --- 6. Save final JSON file ---
    print(f"\n✅ Experiment complete. Saving results to {config['output_file']}...")
    with open(config['output_file'], 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("="*50)
    print("v2 (Final-Fix) experiment completed.")
    print("Next steps:")
    print(f"1. Ensure '{config['output_file']}' has been generated.")
    print(f"2. Run 'comprehensive_analysis_v2_final_fix.py' to evaluate.")
    print("="*50)