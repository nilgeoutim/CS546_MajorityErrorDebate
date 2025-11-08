import transformers
import torch
import json
import numpy as np
import random
from tqdm import tqdm
import re
import time

# =====================================================================================
#  SECTION 1: Prompt Construction (v2)
# =====================================================================================

def construct_actor_prompt(question: str) -> list:
    # Construct Round_1 Actor Prompt (No change)
    return [
        {"role": "system", "content": "You are a helpful assistant that solves math problems. Think step by step."},
        {"role": "user", "content": f"Can you solve the following math problem? {question}\n\nExplain your reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step."}
    ]

def construct_critic_prompt(question: str, solution: str) -> list:
    """
    (v2 Change) A hint for building the 'Critic' score.
    Now requires a CoT 'verification_step' *inside* the JSON to improve score quality.
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
2.  `logic_score` (int, 1-10): Based on your verification, rate the logical coherence.
3.  `computation_score` (int, 1-10): Based on your verification, rate the computation accuracy.
4.  `critique` (str, 1-2 sentences): A brief explanation for your scores.

Your response MUST be only the JSON object.
"""}
    ]

def construct_debate_prompt(question: str, self_analysis: dict, other_analyses: list) -> list:
    """ 
    (v2 Change) Hints for constructing the Round_2 of Actors Debaters.
    Now includes a *quantified threshold* ("at least 2 points higher")
    to make the adaptive threshold less subjective.
    """
    
    # Format your(current agent) previous analysis
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
- Logic: {self_logic}/10
- Computation: {self_comp}/10
- Critique: {self_critique}
"""

    # Formatting analysis of other agents
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
- Logic: {other_logic}/10
- Computation: {other_comp}/10
- Critique: {other_critique}
---
"""

    # v2 Change: Added quantified threshold (item 1)
    system_prompt = "You are a debater in a multi-agent debate. Your goal is to find the *most accurate* answer to the math problem by re-evaluating your own solution against the solutions and critiques from other agents."
    user_prompt = f"""
The original math problem is:
{question}

You and other agents have all proposed solutions and received critiques. Now, you must re-evaluate everything to provide a final, definitive answer.

{self_prompt_part}
{other_prompt_part}

--- YOUR TASK (Round 2) ---
Carefully re-evaluate your own solution and the other agents' solutions, paying close attention to the logic, computation, and critiques.

1.  **(Quantified Threshold)** If you find another agent's solution is demonstrably better (e.g., its `logic_score` is **at least 2 points higher** than your own AND your own re-evaluation confirms it), you should adopt its reasoning and answer.
2.  **(Minority Defense)** Conversely, if you are confident your solution is correct and other agents are wrong (even if they have high scores), *do not* conform. Defend your solution and clearly explain *why* their logic or scores are incorrect.
3.  Provide your final, step-by-step reasoning.
4.  Conclude with your final answer in the form \\boxed{{answer}}.

Let's think step by step again.
"""
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

# =====================================================================================
#  SECTION 2: Helpers Functions (v2)
# =====================================================================================

def read_jsonl(path: str) -> list:
    """JSONL Reader"""
    with open(path, 'r', encoding='utf-8') as fh:
        return [json.loads(line) for line in fh.readlines() if line]

def parse_critic_output(text: str) -> dict:
    """
    (v2 Change) Safely extract 4-key JSON from Llama's output.
    Use regular expressions to find the content between the first '{' and the last '}'.
    """
    default_score = {
        "verification_step": "Error: Could not parse output.",
        "logic_score": 0, 
        "computation_score": 0, 
        "critique": "Error parsing output."
    }
    try:
        # Find JSON that is surrounded by or exposed `json ...`.
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            json_str = match.group(0)
            data = json.loads(json_str)
            # v2 Change: Check for all 4 keys
            if 'logic_score' in data and 'computation_score' in data and 'critique' in data and 'verification_step' in data:
                return {
                    "verification_step": str(data.get("verification_step", "")),
                    "logic_score": int(data.get("logic_score", 0)),
                    "computation_score": int(data.get("computation_score", 0)),
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
    
    # outputs[0]["generated_text"] is a list, last elements is respond from the agent
    generated_text = outputs[0]["generated_text"][-1]['content']
    return generated_text

# =====================================================================================
#  SECTION 3: Main Execution
# =====================================================================================

if __name__ == "__main__":
    agents = 3
    model_id = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    data_file = "gsm_test.jsonl"
    # this is v2 so nameing also is v2
    output_file = f"gsm_critic_actor_{agents}_2_v2.json" 
    
    print("="*50)
    print(f"Start Critic-Actor (v2) Experiment")
    print(f"Model: {model_id}")
    print(f"Agents_counts: {agents}")
    print(f"Output_files: {output_file}")
    print("="*50)

    # --- 2. Loading... ---
    print("Loading Llama 3.1, go grab a coffee...")
    pipeline = transformers.pipeline(
        "text-generation",
        model=model_id,
        model_kwargs={"torch_dtype": torch.bfloat16},
        device_map="auto",
    )
    print("✅ Llama 3.1 Loaded.")

    # --- 3. Load Data ---
    print(f"Data Loading {data_file}...")
    try:
        questions = read_jsonl(data_file)
        random.seed(0)
        random.shuffle(questions)
        # here still do 100 for smoke test
        questions_subset = questions[:100]
        print(f"✅ Data Loaded, processing {len(questions_subset)} problems.")
    except FileNotFoundError:
        print(f"❌ Error: Cant find data '{data_file}'.")
        print("Make sure 'gsm_test.jsonl' [cite: `gsm/gsm_test.json`] the file and this script are located in the same directory.")
        exit()

    # --- 4. Lets go ---
    results = {}
    
    for data in tqdm(questions_subset, desc="Procsessing Questions"):
        question = data['question']
        ground_truth = data['answer']
        
        round_1_results = []
        
        # --- Stage 1: Actor ---
        actor_prompts = [construct_actor_prompt(question) for _ in range(agents)]
        actor_solutions = []
        for i in range(agents):
            solution_text = call_pipeline(
                pipeline, actor_prompts[i],
                max_tokens=1024,
                do_sample=True, temp=0.7, top_p=0.9 
            )
            actor_solutions.append(solution_text)
            time.sleep(0.1) # Minimal API gaps

        # --- Stage 2: Critic ---
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

        # Save Round 1 results
        for sol, score in zip(actor_solutions, critic_scores):
            round_1_results.append({"solution": sol, "score": score})

        # --- Stage 3: Actor V2 (Debate) ---
        debate_prompts = []
        for i in range(agents):
            self_analysis = round_1_results[i]
            other_analyses = round_1_results[:i] + round_1_results[i+1:]
            debate_prompts.append(construct_debate_prompt(question, self_analysis, other_analyses))

        final_solutions = []
        for i in range(agents):
            final_solution_text = call_pipeline(
                pipeline, debate_prompts[i],
                # Keeping 1024 as requested
                max_tokens=1024, 
                do_sample=True, temp=0.7, top_p=0.9
            )
            final_solutions.append(final_solution_text)
            time.sleep(0.1)

        # --- Stage 4: Critic v2 (Final) ---
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

        # Save Final Round results
        final_round_results = []
        for sol, score in zip(final_solutions, final_critic_scores):
            final_round_results.append({"solution": sol, "score": score})
            
        # --- 5. Save result for current question ---
        results[question] = {
            "ground_truth": ground_truth,
            "round_1_results": round_1_results,
            "final_round_results": final_round_results
        }

    # --- 6. Record in to JSON ---
    print(f"\n✅ IS DONE, Saving to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("="*50)
    print("v2 experiment completed.")
    print("Next step:")
    print("1. Ensure 'gsm_critic_actor_3_2_v2.json' has been generated.")
    print("2. Run 'comprehensive_analysis_v2.py' to evaluate this new file.")
    print("="*50)