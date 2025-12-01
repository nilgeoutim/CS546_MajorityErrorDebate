import openai
import json
import numpy as np
import random
from tqdm import tqdm
import re
import time
import os
import math
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =====================================================================================
#  SECTION 1: Role Definitions (Triadic Decoupling)
# =====================================================================================

def construct_actor_prompt(question: str, persona: str) -> list:
    """Constructs the Round 1 Actor Prompt based on Triadic Decoupling."""
    
    if persona == "executor":
        # Agent 1: The Pythonic Executor (PoT)
        system_content = (
            "You are a computational engine. Do NOT use natural language reasoning. "
            "Translate the logic directly into Python code. "
            "MUST define all variables explicitly. "
            "Strictly NO magic numbers. "
            "Output ONLY the Python code block."
        )
        user_content = f"Problem: {question}\n\nWrite a Python script to solve this. Wrap in ```python ... ```."
        
    elif persona == "critic":
        # Agent 2: The Adversarial Critic (Devil's Advocate)
        system_content = (
            "You are a pathological skeptic. Assume the intuitive answer is WRONG. "
            "Look for 'unit traps', 'boundary errors', and 'negative constraints' (e.g., 'remaining', 'without'). "
            "First list the traps, then solve carefully."
        )
        user_content = f"Problem: {question}\n\nIdentify traps and solve. Final answer in \\boxed{{}}."
        
    elif persona == "synthesizer":
        # Agent 3: The Socratic Synthesizer (Dependency Mapper)
        system_content = (
            "You are a semantic linguist. Before calculating, map the 'Dependency Graph' of the problem. "
            "Identify relationships between entities (e.g., 'A depends on B'). "
            "Always map each numerical entity to its semantic role (e.g., cost, duration, count) before calculating. "
            "Clarify any semantic ambiguities."
        )
        user_content = f"Problem: {question}\n\nMap dependencies then solve. Final answer in \\boxed{{}}."
        
    else:
        system_content = "You are a helpful assistant."
        user_content = f"Solve: {question}"

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content}
    ]

# =====================================================================================
#  SECTION 2: High-Signal Rubric (Trap_Aware_Confidence_Score)
# =====================================================================================

def construct_blind_review_prompt(question: str, candidates: list) -> list:
    """
    Constructs the Round 2 Blind Review Prompt.
    Agents evaluate anonymized candidates using the High-Signal Rubric.
    """
    
    candidates_text = ""
    for idx, (label, solution) in enumerate(candidates):
        candidates_text += f"""
--- CANDIDATE {label} ---
{solution}
-----------------------
"""

    system_prompt = (
        "You are a Blind Judge. Evaluate the following anonymous solutions based ONLY on logical rigor. "
        "Do NOT consider who generated them. Look for common hallucinations."
    )
    
    user_prompt = f"""
Original Problem:
{question}

Here are the candidate solutions:
{candidates_text}

For EACH candidate, provide a JSON evaluation using this 'Trap_Aware_Confidence_Score' rubric:

{{
  "candidate": "A",
  "dimensions": {{
    "Variable_Completeness": {{ "score": 0-10, "reason": "Are all entities explicitly defined?" }},
    "Constraint_Satisfaction": {{ "score": 0-10, "reason": "Does it satisfy negative constraints?" }},
    "Code_Logic_Consistency": {{ "score": 0-10, "reason": "Does logic match narrative?" }},
    "Trap_Detection": {{ "score": 0-10, "reason": "Did it catch common traps (Unit Conversion, Boundary Omission, Negative Propositions)?" }}
  }},
  "final_score": (Sum of weighted scores: Var*0.3 + Const*0.3 + Code*0.2 + Trap*0.2),
  "critique": "Brief summary."
}}

Output a list of JSON objects, one for each candidate, wrapped in ```json ... ```.
"""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

def construct_correction_prompt(question: str, original_solution: str, blind_feedback: str) -> list:
    """
    Round 3: Agent corrects their own solution based on blind feedback.
    """
    return [
        {"role": "system", "content": "You are a rational problem solver. Update your solution if the feedback is convincing."},
        {"role": "user", "content": f"""
Original Problem: {question}

Your Previous Solution:
{original_solution}

Blind Peer Reviews:
{blind_feedback}

Task:
1. Analyze the feedback.
2. If you were wrong, admit it and provide the CORRECTED solution.
3. If you were right, defend your logic.
4. Final answer in \\boxed{{}}.
"""}
    ]

# =====================================================================================
#  SECTION 3: Helper Functions
# =====================================================================================

def execute_python_code(code_str: str) -> str:
    """Executes Python code and returns stdout."""
    match = re.search(r'```python\s*(.*?)\s*```', code_str, re.DOTALL)
    if not match:
        return "Error: No Python code block found."
    code = match.group(1)
    
    import io
    import sys
    old_stdout = sys.stdout
    redirected_output = io.StringIO()
    sys.stdout = redirected_output
    
    try:
        # Safe-ish globals - Restrict IO and dangerous builtins
        allowed_builtins = {
            name: getattr(__builtins__, name)
            for name in dir(__builtins__)
            if name not in ['open', 'input', 'eval', 'exec', 'compile', '__import__', 'exit', 'quit', 'help']
        }
        safe_globals = {"__builtins__": allowed_builtins, "math": math, "random": random, "np": np, "print": print}
        
        exec(code, safe_globals)
        output = redirected_output.getvalue()
        if not output.strip():
            return "Code executed but printed nothing."
        return f"Code Execution Output:\n{output}"
    except Exception as e:
        return f"Code Execution Error: {e}"
    finally:
        sys.stdout = old_stdout

def parse_rubric_output(text: str) -> list:
    """Parses the list of JSON rubric scores with enhanced robustness."""
    try:
        # 1. Try finding JSON list
        match = re.search(r'```json\s*(\[.*?\])\s*```', text, re.DOTALL)
        json_str = match.group(1) if match else None
        
        # 2. Try finding single JSON object
        if not json_str:
            match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if match:
                json_str = f"[{match.group(1)}]" # Wrap in list
        
        # 3. Fallback: Find raw list or object without code blocks
        if not json_str:
             match = re.search(r'(\[.*\])', text, re.DOTALL)
             if match: json_str = match.group(1)
        
        if not json_str:
             match = re.search(r'(\{.*\})', text, re.DOTALL)
             if match: json_str = f"[{match.group(1)}]"

        if not json_str:
            return []

        # Sanitize: Remove comments, fix trailing commas
        json_str = re.sub(r'//.*', '', json_str) # Remove single line comments
        json_str = re.sub(r',\s*\]', ']', json_str) # Trailing comma in list
        json_str = re.sub(r',\s*\}', '}', json_str) # Trailing comma in object
        
        return json.loads(json_str)
    except:
        return []

def extract_boxed_answer(text: str) -> str:
    """Extracts the number inside \\boxed{}."""
    match = re.search(r'\\boxed\{([^\}]+)\}', text)
    if match:
        return match.group(1)
    # Fallback: look for last number
    numbers = re.findall(r'-?\d+\.?\d*', text)
    if numbers:
        return numbers[-1]
    return "Error"

def call_openai_api(client, messages, model_id):
    try:
        completion = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=2048,
            temperature=0.7 # Slight creativity for diversity
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"API Error: {e}")
        return ""

# =====================================================================================
#  SECTION 4: Main Execution Loop (The Blind Protocol)
# =====================================================================================

if __name__ == "__main__":
    # Configuration
    config = {
        'agents': 3,
        'model_id': 'gpt-3.5-turbo',
        'data_file': 'gsm/gsm_majority_error.jsonl',
        'output_file': 'gsm/gsm_critic_actor_3_7.json',
        'questions_to_process': 100
    }

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set.")
        exit(1)
    client = openai.OpenAI(api_key=api_key)

    print(f"Starting Deep Research Protocol: {config['output_file']}")
    
    # Load Data
    with open(config['data_file'], 'r', encoding='utf-8') as f:
        questions = [json.loads(line) for line in f.readlines() if line]
    questions = questions[:config['questions_to_process']]

    results = {}

    for data in tqdm(questions, desc="Processing"):
        question = data['question']
        ground_truth = data['answer']
        
        # --- Round 1: Generation (Triadic Decoupling) ---
        roles = ["executor", "critic", "synthesizer"]
        r1_solutions = []
        
        for i, role in enumerate(roles):
            prompt = construct_actor_prompt(question, role)
            resp = call_openai_api(client, prompt, config['model_id'])
            
            # If executor, run code
            if role == "executor":
                exec_out = execute_python_code(resp)
                resp += f"\n\n{exec_out}"
            
            r1_solutions.append({"role": role, "solution": resp, "id": i})

        # --- Round 2: Blind Review ---
        # Anonymize and Shuffle
        candidates = []
        labels = ["A", "B", "C"]
        shuffled_indices = list(range(3))
        random.shuffle(shuffled_indices)
        
        mapping = {} # Label -> Original Index
        
        for idx, original_idx in enumerate(shuffled_indices):
            label = labels[idx]
            sol = r1_solutions[original_idx]['solution']
            candidates.append((label, sol))
            mapping[label] = original_idx

        # Agents Vote (Blindly)
        blind_reviews = []
        # We ask all 3 agents to act as judges
        judge_prompt = construct_blind_review_prompt(question, candidates)
        
        # Aggregate scores
        # Structure: {original_idx: [score1, score2, ...]}
        scores_map = {0: [], 1: [], 2: []}
        
        for i in range(3):
            # Each agent judges
            review_json_str = call_openai_api(client, judge_prompt, config['model_id'])
            reviews = parse_rubric_output(review_json_str)
            blind_reviews.append(reviews)
            
            for review in reviews:
                label = review.get("candidate")
                score = review.get("final_score", 0)
                if label in mapping:
                    orig_idx = mapping[label]
                    scores_map[orig_idx].append(score)

        # --- Round 3: Correction ---
        # Agents see the reviews for THEIR solution (de-anonymized)
        final_answers = []
        
        for i in range(3):
            # Gather relevant feedback
            my_feedback = ""
            for agent_reviews in blind_reviews:
                for r in agent_reviews:
                    # Find which label corresponded to me
                    # We need to reverse map: which label maps to 'i'?
                    my_label = None
                    for l, oid in mapping.items():
                        if oid == i:
                            my_label = l
                            break
                    
                    if r.get("candidate") == my_label:
                        my_feedback += f"- Judge: {r.get('critique')} (Score: {r.get('final_score')})\n"

            corr_prompt = construct_correction_prompt(question, r1_solutions[i]['solution'], my_feedback)
            final_resp = call_openai_api(client, corr_prompt, config['model_id'])
            
            # FIX: Execute code if present (Critical for Executor in Round 3)
            if "```python" in final_resp:
                 exec_out = execute_python_code(final_resp)
                 final_resp += f"\n\n{exec_out}"
            
            # Extract answer
            ans = extract_boxed_answer(final_resp)
            final_answers.append({"answer": ans, "full_text": final_resp, "original_idx": i})

        # --- Weighted Voting Algorithm (Conservative Strategy) ---
        # Consensus > Outlier. Alpha=1.0, Threshold=4.0
        
        unique_answers = {} 
        alpha = 1.0 
        max_score = 10.0
        score_threshold = 4.0
        
        # Track raw scores for fallback
        raw_scores_map = {} 

        for i in range(3):
            ans = final_answers[i]['answer']
            if ans == "Error": continue
            
            # Calculate raw average score
            raw_avg = np.mean(scores_map[i]) if scores_map[i] else 0.0
            raw_scores_map[ans] = max(raw_scores_map.get(ans, 0), raw_avg) # Keep highest score for this answer

            # Safety Gate: Filter out low-quality logic
            if raw_avg < score_threshold:
                continue

            # Normalize to 0-1
            norm_score = max(0.0, min(1.0, raw_avg / max_score))
            
            # Weight calculation
            weight = math.exp(alpha * norm_score)
            
            if ans not in unique_answers:
                unique_answers[ans] = 0
            unique_answers[ans] += weight

        # Select Winner
        fallback_triggered = False
        if unique_answers:
            best_ans = max(unique_answers, key=unique_answers.get)
        else:
            # Fallback: All failed threshold, pick "least bad" (highest raw score)
            fallback_triggered = True
            if raw_scores_map:
                best_ans = max(raw_scores_map, key=raw_scores_map.get)
            else:
                best_ans = "Error"
        
        results[question] = {
            "ground_truth": ground_truth,
            "final_decision": best_ans,
            "fallback_triggered": fallback_triggered,
            "round_1": r1_solutions,
            "round_2_scores": scores_map,
            "round_3_finals": final_answers,
            "voting_weights": unique_answers
        }

    # Save
    with open(config['output_file'], 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    
    print(f"Done. Saved to {config['output_file']}")