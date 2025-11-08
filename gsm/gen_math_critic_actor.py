import transformers
import torch
import json
import numpy as np
import random
from tqdm import tqdm
import re
import time

# =====================================================================================
#  SECTION 1: Prompt Construction (v2-Fix, Iteration 2)
# =====================================================================================

def construct_actor_prompt(question: str) -> list:
    """Constructs the Round 1 Actor Prompt."""
    return [
        {"role": "system", "content": "You are a helpful assistant that solves math problems. Think step by step."},
        {"role": "user", "content": f"Can you solve the following math problem? {question}\n\nExplain your reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step."}
    ]

def construct_critic_prompt(question: str, solution: str) -> list:
    """
    (v2-Fix Iteration) Constructs the 'Critic' prompt.
    1. Requires 'verification_step' CoT.
    2. (NEW) Requires 0.5-step floating point scores for granularity.
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

Please evaluate this solution. You MUST provide your evaluation in a single JSON object with FOUR keys:
1.  `verification_step` (str): First, briefly verify a key calculation or logic step. (e.g., "Verified step 2: 30 / 60 = 0.5. This is correct.")
2.  `logic_score` (float, 1.0-10.0): Based on your verification, rate the logical coherence. Use 0.5 steps (e.g., 8.0, 8.5, 9.0).
3.  `computation_score` (float, 1.0-10.0): Based on your verification, rate the computation accuracy. Use 0.5 steps.
4.  `critique` (str, 1-2 sentences): A brief explanation for your scores.

Your response MUST be only the JSON object.
"""}
    ]

def construct_debate_prompt(question: str, self_analysis: dict, other_analyses: list) -> list:
    """ 
    (v2-Fix Iteration) Constructs the Round 2 'Debater' prompt.
    1. (NEW) Includes multi-dimensional (Logic OR Comp) threshold.
    2. (NEW) Uses float scores for comparison.
    """
    
    # Format the current agent's previous analysis
    self_solution = self_analysis['solution']
    # (NEW) Handle float scores
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

    # (v2-Fix Iteration) Added multi-dimensional (OR) threshold
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
    """(NEW) Robustly convert a value to float, handling strings, int, etc."""
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
    (v2-Fix Iteration) Safely extract the 4-key JSON and parse floats.
    """
    default_score = {
        "verification_step": "Error: Could not parse output.",
        "logic_score": 0.0, 
        "computation_score": 0.0, 
        "critique": "Error parsing output."
    }
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            json_str = match.group(0)
            data = json.loads(json_str)
            if 'logic_score' in data and 'computation_score' in data and 'critique' in data and 'verification_step' in data:
                return {
                    "verification_step": str(data.get("verification_step", "")),
                    # (NEW) Use safe float parser
                    "logic_score": _safe_parse_float(data.get("logic_score")),
                    "computation_score": _safe_parse_float(data.get("computation_score")),
                    "critique": str(data.get("critique", ""))
                }
            else:
                return default_score
        else:
            return default_score
    except Exception as e:
        print(f"\n[Warning] Failed to parse critic JSON: {e}\nText was: {text}\n")
        return default_score

def call_pipeline(pipeline, messages, max_tokens, do_sample, temp, top_p):
    """Helper function to call the generation pipeline."""
    terminators = [
        pipeline.tokenizer.eos_token_id,
        pipeline.tokenizer.convert_tokens_to_ids("<|eot_id|>")
    ]
    
    outputs = pipeline(
        messages,
        max_new_tokens=max_tokens,
        eos_token_id=terminators,
        do_sample=do_sample,
        temperature=temp if do_sample else None,
        top_p=top_p if do_sample else None,
    )
    
    generated_text = outputs[0]["generated_text"][-1]['content']
    return generated_text

# =====================================================================================
#  SECTION 3: Main Execution
# =====================================================================================

if __name__ == "__main__":
    agents = 3
    model_id = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    data_file = "gsm_test.jsonl"
    # This is the 2nd iteration of v2-fix, output file reflects that.
    output_file = f"gsm_critic_actor_{agents}_2_v2_fix_iter2.json" 
    
    print("="*50)
    print(f"Starting Critic-Actor (v2-Fix, Iteration 2) Experiment")
    print(f"Model: {model_id}")
    print(f"Agent Count: {agents}")
    print(f"Output File: {output_file}")
    print("="*50)

    # --- 1. Load Model ---
    print("Loading Llama 3.1, please wait...")
    pipeline = transformers.pipeline(
        "text-generation",
        model=model_id,
        model_kwargs={"torch_dtype": torch.bfloat16},
        device_map="auto",
    )
    print("✅ Llama 3.1 Loaded.")

    # --- 2. Load Data ---
    print(f"Loading data from {data_file}...")
    try:
        questions = read_jsonl(data_file)
        random.seed(0)
        random.shuffle(questions)
        # Processing 100 questions for a smoke test
        questions_subset = questions[:100]
        print(f"✅ Data Loaded. Processing {len(questions_subset)} problems.")
    except FileNotFoundError:
        print(f"❌ Error: Data file not found at '{data_file}'.")
        print("Please ensure 'gsm_test.jsonl' is in the same directory.")
        exit()

    # --- 3. Run Experiment ---
    results = {}
    
    for data in tqdm(questions_subset, desc="Processing Questions"):
        question = data['question']
        ground_truth = data['answer']
        
        round_1_results = []
        
        # --- Stage 1: Initial Actor Solutions ---
        actor_prompts = [construct_actor_prompt(question) for _ in range(agents)]
        actor_solutions = []
        for i in range(agents):
            solution_text = call_pipeline(
                pipeline, actor_prompts[i],
                max_tokens=1024,
                do_sample=True, temp=0.7, top_p=0.9 
            )
            actor_solutions.append(solution_text)
            time.sleep(0.1) 

        # --- Stage 2: Initial Critic Scores ---
        critic_prompts = [construct_critic_prompt(question, sol) for sol in actor_solutions]
        critic_scores = []
        for i in range(agents):
            score_text = call_pipeline(
                pipeline, critic_prompts[i],
                max_tokens=256,
                do_sample=False, temp=None, top_p=None
            )
            critic_scores.append(parse_critic_output(score_text))
            time.sleep(0.1)

        # Collate Round 1 results
        for sol, score in zip(actor_solutions, critic_scores):
            round_1_results.append({"solution": sol, "score": score})

        # --- Stage 3: Actor Debate (v2-Fix Iteration) ---
        debate_prompts = []
        for i in range(agents):
            self_analysis = round_1_results[i]
            other_analyses = round_1_results[:i] + round_1_results[i+1:]
            debate_prompts.append(construct_debate_prompt(question, self_analysis, other_analyses))

        final_solutions = []
        for i in range(agents):
            final_solution_text = call_pipeline(
                pipeline, debate_prompts[i],
                max_tokens=1024, # Kept at 1024 as requested
                do_sample=True, temp=0.7, top_p=0.9
            )
            final_solutions.append(final_solution_text)
            time.sleep(0.1)

        # --- Stage 4: Final Critic Scores ---
        final_critic_prompts = [construct_critic_prompt(question, sol) for sol in final_solutions]
        final_critic_scores = []
        for i in range(agents):
            final_score_text = call_pipeline(
                pipeline, final_critic_prompts[i],
                max_tokens=256,
                do_sample=False, temp=None, top_p=None
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
    print(f"\n✅ Experiment complete. Saving results to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("="*50)
    print("v2 (Stalemate Fix, Iteration 2) experiment completed.")
    print("Next steps:")
    print(f"1. Ensure '{output_file}' has been generated.")
    print(f"2. Run 'comprehensive_analysis_v2_fix.py' (with float fix) to evaluate.")
    print("="*50)