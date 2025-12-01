import openai
import json
import numpy as np
import random
from tqdm import tqdm
import re
import time
import openai
import json
import numpy as np
import random
from tqdm import tqdm
import re
import time
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =====================================================================================
#  SECTION 1: Prompt Construction (v2-Final-Fix)
# =====================================================================================

def construct_actor_prompt(question: str, persona: str = "default") -> list:
    """Constructs the Round 1 Actor Prompt with Persona Support."""
    
    if persona == "logician":
        return [
            {"role": "system", "content": "You are a logical thinker. Solve this problem step-by-step. Break down complex logic into simple, sequential steps."},
            {"role": "user", "content": f"Can you solve the following math problem? {question}\n\nExplain your reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step."}
        ]
    elif persona == "programmer":
        return [
            {"role": "system", "content": "You are a Python expert. Write a Python script to solve this math problem. The script must print the final answer. Do NOT explain with words, just write the code."},
            {"role": "user", "content": f"Problem: {question}\n\nWrite a Python script that calculates the answer and prints it. Wrap the code in ```python ... ```."}
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

def construct_critic_prompt(question: str, solution: str) -> list:
    """
    (v2-Final-Fix) Constructs the 'Critic' prompt.
    """
    return [
        {"role": "system", "content": "You are a Critic agent. Evaluate the solution based on logic and computation. Provide output in JSON."},
        {"role": "user", "content": f"""Here is the math problem:
---
{question}
---

Here is the proposed solution:
---
{solution}
---

Evaluate this solution. Provide your evaluation in a single JSON object inside a markdown code block (```json ... ```) with FOUR keys:
1.  `verification_step` (str): Verify a key calculation.
2.  `logic_score` (float, 1.0-10.0): Rate logical coherence.
3.  `computation_score` (float, 1.0-10.0): Rate computation accuracy.
4.  `critique` (str): Brief explanation.

Example format:
```json
{{
    "verification_step": "Verified 12+12=24. Correct.",
    "logic_score": 9.5,
    "computation_score": 10.0,
    "critique": "Perfect logic and calculation."
}}
```
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
--- YOUR PREVIOUS ANALYSIS ---
Your Solution:
```
{self_solution}
```
Your Scores: Logic: {self_logic}, Comp: {self_comp}
Critique: {self_critique}
"""

    # Format other agents' analyses
    other_prompt_part = "\n--- OTHER AGENTS' ANALYSES ---\n"
    if not other_analyses:
        other_prompt_part += "No other agents provided analysis.\n"
    else:
        for i, analysis in enumerate(other_analyses):
            other_solution = analysis['solution']
            other_logic = analysis['score']['logic_score']
            other_comp = analysis['score']['computation_score']
            other_critique = analysis['score']['critique']
            other_prompt_part += f"""
Agent {i+1}:
Solution:
```
{other_solution}
```
Scores: Logic: {other_logic}, Comp: {other_comp}
Critique: {other_critique}
---
"""

    system_prompt = "You are a debater. Find the most accurate answer by re-evaluating solutions."
    user_prompt = f"""
Original Problem:
{question}

{self_prompt_part}
{other_prompt_part}

--- YOUR TASK ---
Re-evaluate everything.
1. Adopt another solution ONLY if it is demonstrably better (Logic +2.0 OR Comp +3.0 higher).
2. Defend your solution if you are confident.
3. Provide final step-by-step reasoning and answer in \\boxed{{answer}}.
"""
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

# =====================================================================================
#  SECTION 2: Helper Functions
# =====================================================================================

def execute_python_code(code_str: str) -> str:
    """
    Executes Python code found in the string and returns stdout.
    WARNING: Uses exec(). Only use with trusted/generated code in a controlled env.
    """
    # Extract code block
    match = re.search(r'```python\s*(.*?)\s*```', code_str, re.DOTALL)
    if not match:
        return "Error: No Python code block found."
    
    code = match.group(1)
    
    # Capture stdout
    import io
    import sys
    old_stdout = sys.stdout
    redirected_output = io.StringIO()
    sys.stdout = redirected_output
    
    try:
        # Define a limited global scope to prevent some malicious acts (not a full sandbox)
        # We allow math, random, etc.
        # Actually, for imports to work inside, we might need __builtins__
        
        exec(code, {}) # Use empty locals/globals to limit scope slightly, but standard imports inside code work
        output = redirected_output.getvalue()
        if not output.strip():
            return "Code executed but printed nothing."
        return f"Code Execution Output:\n{output}"
    except Exception as e:
        return f"Code Execution Error: {e}"
    finally:
        sys.stdout = old_stdout

def read_jsonl(path: str) -> list:
    """Reads a JSONL file."""
    with open(path, 'r', encoding='utf-8') as fh:
        return [json.loads(line) for line in fh.readlines() if line]

def _safe_parse_float(value: any, default: float = 0.0) -> float:
    """Robustly convert a value to float."""
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            # Remove non-numeric chars except dot
            clean = re.sub(r'[^\d.]', '', value)
            return float(clean)
        except (ValueError, TypeError):
            return default
    return default

def parse_critic_output(text: str) -> dict:
    """
    Robustly extract JSON from critic output.
    """
    default_score = {
        "verification_step": "Error: Could not parse output.",
        "logic_score": 0.0, 
        "computation_score": 0.0, 
        "critique": "Error parsing output."
    }
    try:
        # Try finding JSON block
        match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        json_str = match.group(1) if match else None
        
        if not json_str:
            # Try finding just braces
            match = re.search(r'\{.*\}', text, re.DOTALL)
            json_str = match.group(0) if match else None
            
        if not json_str:
            return default_score

        # Fix common JSON errors (trailing commas)
        json_str = re.sub(r',\s*\}', '}', json_str)
        
        data = json.loads(json_str)
        
        return {
            "verification_step": str(data.get("verification_step", "")),
            "logic_score": _safe_parse_float(data.get("logic_score")),
            "computation_score": _safe_parse_float(data.get("computation_score")),
            "critique": str(data.get("critique", ""))
        }
            
    except Exception as e:
        # print(f"JSON Parse Error: {e}") # Reduce noise
        return default_score

def call_openai_api(client, messages, gen_config, model_id):
    """Helper function to call the OpenAI API."""
    try:
        completion = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=gen_config['max_tokens'],
            n=1
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return ""

# =====================================================================================
#  SECTION 3: Main Execution Block
# =====================================================================================

if __name__ == "__main__":
    # Configuration
    config = {
        'agents': 3,
        'rounds': 4,
        'model_id': 'gpt-3.5-turbo',
        'data_file': 'gsm/gsm_majority_error.jsonl',
        'output_file': 'gsm/gsm_critic_actor_3_5.json',
        'questions_to_process': 100
    }
    
    actor_gen_config = {'max_tokens': 4096}
    critic_gen_config = {'max_tokens': 4096}

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set.")
        exit(1)
        
    client = openai.OpenAI(api_key=api_key)

    print("="*50)
    print(f"Starting Experiment (True PoT + Contrastive CoT)")
    print(f"Output: {config['output_file']}")
    print("="*50)

    # --- 3. Load Data ---
    try:
        questions = read_jsonl(config['data_file'])
        questions_subset = questions[:config['questions_to_process']]
        print(f"✅ Data Loaded. Processing {len(questions_subset)} problems.")
    except FileNotFoundError:
        print(f"❌ Error: Data file not found.")
        exit()

    # --- 4. Run Experiment ---
    results = {}
    
    for data in tqdm(questions_subset, desc="Processing Questions"):
        question = data['question']
        ground_truth = data['answer']
        
        all_rounds_results = [] 
        
        # --- Round 0: Initial Solutions & Critiques ---
        # 1. Generate Solutions with DIVERSITY
        
        actor_solutions = []
        personas = ["logician", "programmer", "skeptic"]
        
        for i in range(config['agents']):
            persona = personas[i % len(personas)]
            prompt = construct_actor_prompt(question, persona)
            
            response_text = call_openai_api(client, prompt, actor_gen_config, config['model_id'])
            
            # Special handling for Programmer (True PoT)
            if persona == "programmer":
                exec_output = execute_python_code(response_text)
                # Combine code and output for the final solution text
                final_solution = f"{response_text}\n\n--- EXECUTION RESULT ---\n{exec_output}\n\nFinal Answer: \\boxed{{{exec_output.strip().split()[-1] if 'Output:' in exec_output else 'Error'}}}"
                # (Simple heuristic for boxed answer from output, or just let the Critic judge the output)
                # Better: Ask model to format output, but for now we append.
                actor_solutions.append(final_solution)
            else:
                actor_solutions.append(response_text)
        
        # 2. Generate Critiques
        critic_prompts = [construct_critic_prompt(question, sol) for sol in actor_solutions]
        critic_scores = []
        for i in range(config['agents']):
            score_text = call_openai_api(client, critic_prompts[i], critic_gen_config, config['model_id'])
            critic_scores.append(parse_critic_output(score_text))

        # 3. Collate Round 0 results
        current_round_results = []
        for sol, score in zip(actor_solutions, critic_scores):
            current_round_results.append({"solution": sol, "score": score})
        
        all_rounds_results.append(current_round_results)

        # --- Debate Loop (Rounds 1 to N-1) ---
        for r in range(1, config['rounds']):
            previous_results = all_rounds_results[-1]
            
            debate_prompts = []
            for i in range(config['agents']):
                self_analysis = previous_results[i]
                other_analyses = previous_results[:i] + previous_results[i+1:]
                debate_prompts.append(construct_debate_prompt(question, self_analysis, other_analyses))

            # 1. Generate New Solutions (Debate)
            new_solutions = []
            for i in range(config['agents']):
                new_solution_text = call_openai_api(client, debate_prompts[i], actor_gen_config, config['model_id'])
                new_solutions.append(new_solution_text)

            # 2. Generate New Critiques
            new_critic_prompts = [construct_critic_prompt(question, sol) for sol in new_solutions]
            new_critic_scores = []
            for i in range(config['agents']):
                new_score_text = call_openai_api(client, new_critic_prompts[i], critic_gen_config, config['model_id'])
                new_critic_scores.append(parse_critic_output(new_score_text))

            # 3. Collate Current Round results
            current_round_results = []
            for sol, score in zip(new_solutions, new_critic_scores):
                current_round_results.append({"solution": sol, "score": score})
            
            all_rounds_results.append(current_round_results)

        # --- 5. Save result ---
        results[question] = {
            "ground_truth": ground_truth,
            "round_1_results": all_rounds_results[0],
            "final_round_results": all_rounds_results[-1],
            "all_rounds_data": all_rounds_results
        }

    # --- 6. Save final JSON file ---
    print(f"\n✅ Experiment complete. Saving results to {config['output_file']}...")
    with open(config['output_file'], 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("="*50)
    print("True PoT Experiment Completed.")
    print("="*50)