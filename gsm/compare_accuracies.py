import json
import numpy as np
import re
from tqdm import tqdm
import os

# =====================================================================================
# SECTION 1: Core Evaluation Functions (V2 Fixes)
# [Content redacted for brevity, assuming functions remain the same]
# =====================================================================================
def parse_answer(input_str: str) -> str:
# ... (rest of parse_answer)
    """
    (V2) Safer Answer Parser.
    First looks for \boxed{...}.
    If not found, it *only* looks for the number at the end of the string ($).
    This prevents accidentally grabbing numbers like "1" from "Agent 1" or "52" from "52 apples".
    """
    if not isinstance(input_str, str):
        return None
        
    # Pattern 1: \boxed{...}
    pattern_boxed = r"\\boxed\{([0-9.,$]*)\}"
    matches = re.findall(pattern_boxed, input_str)
    solution = None
    for match_str in matches[::-1]:
        # Clean the string by removing all non-numeric and non-dot characters
        solution = re.sub(r"[^0-9.]", "", match_str)
        if solution:
            return solution # Found \boxed{}, return immediately

    # Pattern 2: Number at the end of the string
    # Only triggered if \boxed{} is not found
    pattern_final_num = r"(\d+\.?\d*)\s*$"
    matches = re.findall(pattern_final_num, input_str)
    if matches:
        return matches[-1]
        
    return None

def solve_math_problems(input_str: str) -> str:
# ... (rest of solve_math_problems)
    """(V2 Deprecated) This is a problematic function and should no longer be used as a fallback."""
    # This function is kept only in case, but get_final_decision should not call it anymore.
    pattern = r"\d+\.?\d*"
    matches = re.findall(pattern, input_str)
    if matches:
        return matches[-1]
    return None

def most_frequent(List: list) -> str:
# ... (rest of most_frequent)
    """Finds the majority vote from the list."""
    if not List:
        return None
    counter = 0
    # Use a safe default value
    num = List[0] if List else None 
    
    unique_items = set(List)
    
    for i in unique_items:
        try:
            current_frequency = List.count(i)
            if current_frequency > counter:
                counter = current_frequency
                num = i
        except:
            continue
    return num

def get_ground_truth(gt: str) -> str:
# ... (rest of get_ground_truth)
    """Extracts the ground truth answer digit from the GT string."""
    gt_pattern = r"#### (\d+\.?\d*)"
    gt_match = re.search(gt_pattern, gt)
    if not gt_match:
        # Fallback: If #### tag is not found, take the last number in the GT string
        gt_fallback = re.findall(r"\d+\.?\d*", gt)
        if gt_fallback:
            return gt_fallback[-1]
        return None
    return gt_match.group(1)

def get_final_decision(pred_solutions: list) -> str:
# ... (rest of get_final_decision)
    """
    (V2 Fix) Gets the final majority vote answer from a set of predictions.
    This version *only* uses the safer parse_answer function.
    """
    pred_answers = []
    for pred_solution in pred_solutions:
        # *** V2 FIX ***
        # Only call parse_answer.
        # No longer calls the problematic solve_math_problems(pred_solution) as a fallback.
        pred_answer = parse_answer(pred_solution)
        
        if pred_answer is not None:
            pred_answers.append(pred_answer)
    
    if not pred_answers:
        return None
    
    return most_frequent(pred_answers)

def check_correctness(gt_answer: str, final_pred_answer: str) -> int:
# ... (rest of check_correctness)
    """Compares GT and prediction, returns 1 (correct) or 0 (incorrect)."""
    if gt_answer is None or final_pred_answer is None:
        return 0
    try:
        # Use numpy.isclose for robust float comparison
        return 1 if np.isclose(float(gt_answer), float(final_pred_answer)) else 0
    except (ValueError, TypeError):
        # Handle cases like "1,000" vs "1000"
        try:
            gt_clean = gt_answer.replace(",", "")
            pred_clean = final_pred_answer.replace(",", "")
            return 1 if np.isclose(float(gt_clean), float(pred_clean)) else 0
        except (ValueError, TypeError):
            return 0 # Cannot parse even after cleaning

# =====================================================================================
# SECTION 2: Data Extractors for Different JSON Formats
# [Content redacted for brevity, assuming functions remain the same]
# =====================================================================================
def get_critic_actor_data(response_dict: dict) -> dict:
# ... (rest of get_critic_actor_data)
    """Extracts data from the gsm_critic_actor_3_2.json format [cite: `gsm_critic_actor_3_2.json`]."""
    results = {}
    for question, data in response_dict.items():
        gt_answer = get_ground_truth(data.get("ground_truth", ""))
        
        final_solutions = []
        if "final_round_results" in data:
             final_solutions = [item.get("solution", "") for item in data["final_round_results"]]
        
        final_decision = get_final_decision(final_solutions)
        
        results[question] = {
            "gt_answer": gt_answer,
            "final_decision": final_decision,
            "is_correct": check_correctness(gt_answer, final_decision),
            "full_data": data # Store all data for later analysis
        }
    return results

def get_original_mad_data(response_dict: dict) -> dict:
# ... (rest of get_original_mad_data)
    """Extracts data from the gsm_3_3.json format (Includes 'content' fix) [cite: `gsm_3_3.json`]."""
    results = {}
    for question, data in response_dict.items():
        # The original JSON [cite: `gsm_3_3.json`] structure is [responses_list, gt_string]
        if not (isinstance(data, (list, tuple)) and len(data) == 2):
            continue # Skip incorrectly formatted data
            
        responses, gt = data
        gt_answer = get_ground_truth(gt)
        
        pred_solutions = []
        if not isinstance(responses, list):
            continue # Skip incorrectly formatted 'responses'
            
        for response_context_list in responses:
            if not (isinstance(response_context_list, list) and len(response_context_list) > 0):
                continue
            
            # Fix: Handle cases where 'content' might be a dictionary or a string
            content_value = response_context_list[-1].get('content') # Use .get() to avoid KeyError
            
            if isinstance(content_value, dict) and 'content' in content_value:
                pred_solutions.append(content_value['content'])
            elif isinstance(content_value, str):
                pred_solutions.append(content_value)
            else:
                pred_solutions.append("") # Add empty string to maintain length, parse_answer will skip it
        
        final_decision = get_final_decision(pred_solutions)
        
        results[question] = {
            "gt_answer": gt_answer,
            "final_decision": final_decision,
            "is_correct": check_correctness(gt_answer, final_decision),
            "full_data": {"final_solutions": pred_solutions} # Store data for analysis
        }
    return results

# =====================================================================================
# SECTION 3: Main Analysis and Report Generation
# =====================================================================================

def main():
    # --- 1. Define Filenames ---
    # ** IMPORTANT: ** Ensure filenames match the files you are comparing!
    critic_file = 'gsm_critic_actor_3_2_v2.json' # Evaluating the V2 script output
    original_file = 'gsm_3_3.json'
    report_file = 'analysis_report_v2.md'

    print("="*50)
    print("--- Comprehensive Evaluation Script (V2) ---")
    print(f"Comparing:")
    print(f"  (A) Original MAD: {original_file}")
    print(f"  (B) New Critic-Actor: {critic_file}")
    print("="*50)

    # --- 2. Load JSON Files ---
    print("Loading JSON files...")
    # >>> 临时打印 A
    print("Step A: Attempting to load files...")
    try:
        with open(critic_file, 'r', encoding='utf-8') as f:
            critic_dict = json.load(f)
        with open(original_file, 'r', encoding='utf-8') as f:
            original_dict = json.load(f)
    except FileNotFoundError as e:
        print(f"❌ Error: File not found {e.filename}.")
        print("请确保两个 JSON 文件 [cite: `gsm_3_3.json`] 存在。")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Error: JSON decoding error {e}. The file might be corrupted。")
        return
    
    print("✅ 文件加载完毕。正在提取数据...")
    # --- 3. Extract and Process Data ---
    critic_results = get_critic_actor_data(critic_dict)
    original_results = get_original_mad_data(original_dict)

    # --- 4. Question-by-Question Comparison ---
    print("正在逐个问题对比模型...")
    # >>> 临时打印 B
    print("Step B: Starting comparison...")
    categories = {
        "win": [],       # B correct, A wrong
        "loss": [],      # B wrong, A correct
        "correct": [],   # Both correct
        "incorrect": []  # Both wrong
    }

    # Ensure we only compare questions common to *both* files
    original_questions = set(original_results.keys())
    critic_questions = set(critic_results.keys())
    
    common_questions = list(original_questions & critic_questions)
    
    if not common_questions:
        print("❌ Error: 两个 JSON 文件中没有共同的问题可供比较。")
        return

    for question in tqdm(common_questions, desc="Categorizing results"):
        critic_res = critic_results[question]
        original_res = original_results[question]

        # Compare scores
        a_correct = original_res["is_correct"]
        b_correct = critic_res["is_correct"]
        
        if b_correct == 1 and a_correct == 0:
            categories["win"].append(question)
        elif b_correct == 0 and a_correct == 1:
            categories["loss"].append(question)
        elif b_correct == 1 and a_correct == 1:
            categories["correct"].append(question)
        elif b_correct == 0 and a_correct == 0:
            categories["incorrect"].append(question)

    # --- 5. Print Terminal Summary ---
    # >>> 临时打印 C
    print(f"Step C: Comparison finished. Found {len(common_questions)} common questions.")
    
    total_questions = len(common_questions)
    
    # Avoid division by zero
    acc_original = (len(categories['loss']) + len(categories['correct'])) / total_questions * 100 if total_questions > 0 else 0
    acc_critic = (len(categories['win']) + len(categories['correct'])) / total_questions * 100 if total_questions > 0 else 0
    improvement = acc_critic - acc_original

    print("\n" + "="*40)
    print("--- Comprehensive Evaluation Results (V2) ---")
    print(f"Total Questions Compared: {total_questions}")
    print("="*40)
    print(f"Original MAD ({original_file}):")
    print(f"   - Accuracy: {acc_original:.1f}%")
    print(f"Critic-Actor ({critic_file}):")
    print(f"   - Accuracy: {acc_critic:.1f}%")
    print("="*40)
    print(f"Performance Improvement (Critic-Actor vs. Original): {improvement:+.1f} percentage points")
    print("="*40)
    print("--- Detailed Categorization ---")
    print(f"✅ Win (Critic-Actor Wins): {len(categories['win'])} questions")
    print(f"❌ Loss (Critic-Actor Loses): {len(categories['loss'])} questions")
    print(f"👍 Correct (Both Correct): {len(categories['correct'])} questions")
    print(f"👎 Incorrect (Both Incorrect): {len(categories['incorrect'])} questions")
    print("="*40)

    # --- 6. Generate Detailed Markdown Report ---
    print(f"正在生成详细报告: {report_file} ...")
    with open(report_file, 'w', encoding='utf-8') as f:
# ... (rest of report generation)
        f.write(f"# Experiment Comparison Analysis Report (V2)\n\n")
        f.write("This document details the performance differences between the `Original MAD` and the `Critic-Actor` (V2) models on the GSM8K task.\n\n")
        
        f.write("## Summary\n")
        f.write(f"| Model | Accuracy |\n")
        f.write(f"| :--- | :--- |\n")
        f.write(f"| Original MAD ({original_file}) | {acc_original:.1f}% |\n")
        f.write(f"| Critic-Actor ({critic_file}) | {acc_critic:.1f}% |\n\n")
        
        f.write("## Categorized Statistics\n")
        f.write(f"| Category | Description | Count |\n")
        f.write(f"| :--- | :--- | :--- |\n")
        f.write(f"| ✅ Win | Critic-Actor correct, Original MAD wrong | {len(categories['win'])} |\n")
        f.write(f"| ❌ Loss | Critic-Actor wrong, Original MAD correct | {len(categories['loss'])} |\n")
        f.write(f"| 👍 Correct | Both Correct | {len(categories['correct'])} |\n")
        f.write(f"| 👎 Incorrect | Both Incorrect | {len(categories['incorrect'])} |\n\n")
        f.write(f"**Net Performance Improvement: {improvement:+.1f} percentage points**\n\n")

        # --- Detailed Analysis: Failure Cases (Losses) ---
        f.write("="*20 + "\n\n")
        f.write(f"## ❌ Failure Case Analysis (Losses) - {len(categories['loss'])} Questions\n\n")
        f.write("In these cases, the **Original MAD was correct**, but the **Critic-Actor model was wrong**. This highlights a failure mode that needs analysis.\n\n")
        
        if not categories["loss"]:
            f.write("No failure cases! 🎉\n\n")
            
        for i, question in enumerate(categories["loss"]):
            critic_data = critic_results[question]
            original_data = original_results[question]
            
            f.write(f"### Loss #{i+1}: {question}\n\n")
            f.write(f"**Ground Truth (GT):** `{critic_data.get('gt_answer', 'N/A')}`\n\n")
            f.write(f"**Original MAD Decision (Correct):** `{original_data.get('final_decision', 'N/A')}`\n")
            f.write(f"**Critic-Actor Decision (Wrong):** `{critic_data.get('final_decision', 'N/A')}`\n\n")
            f.write(f"**Detailed Data (Critic-Actor Model):**\n")
            
            f.write("#### Round 1 (Initial Solutions and Scores):\n")
            if "round_1_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["round_1_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A')}, Comp: {score.get('computation_score', 'N/A')})**:\n")
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
                    f.write(f"  - Solution:\n```\n{item.get('solution', 'N/A')}\n```\n")
            
            f.write("\n#### Round 2 (Final Solutions and Scores):\n")
            if "final_round_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["final_round_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A')}, Comp: {score.get('computation_score', 'N/A')})**:\n")
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
                    f.write(f"  - Solution:\n```\n{item.get('solution', 'N/A')}\n```\n")
            f.write("\n---\n")

        # --- Detailed Analysis: Success Cases (Wins) ---
        f.write("="*20 + "\n\n")
        f.write(f"## ✅ Success Case Analysis (Wins) - {len(categories['win'])} Questions\n\n")
        f.write("In these cases, the **Original MAD was wrong**, but the **Critic-Actor model was correct**. This validates the effectiveness of the new framework.\n\n")

        if not categories["win"]:
            f.write("No success cases.\n\n")

        for i, question in enumerate(categories["win"]):
            critic_data = critic_results[question]
            original_data = original_results[question]
            
            f.write(f"### Win #{i+1}: {question}\n\n")
            f.write(f"**Ground Truth (GT):** `{critic_data.get('gt_answer', 'N/A')}`\n\n")
            f.write(f"**Original MAD Decision (Wrong):** `{original_data.get('final_decision', 'N/A')}`\n")
            f.write(f"**Critic-Actor Decision (Correct):** `{critic_data.get('final_decision', 'N/A')}`\n\n")
            f.write(f"**Detailed Data (Critic-Actor Model):**\n")

            f.write("#### Round 1 (Initial Solutions and Scores):\n")
            if "round_1_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["round_1_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A')}, Comp: {score.get('computation_score', 'N/A')})**:\n")
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
                    f.write(f"  - Solution:\n```\n{item.get('solution', 'N/A')}\n```\n")
            
            f.write("\n#### Round 2 (Final Solutions and Scores):\n")
            if "final_round_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["final_round_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A')}, Comp: {score.get('computation_score', 'N/A')})**:\n")
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
                    f.write(f"  - Solution:\n```\n{item.get('solution', 'N/A')}\n```\n")
            f.write("\n---\n")

    print(f"✅ Success! Detailed report saved to: {report_file}")
    print("Open the file to analyze the new 'Loss' cases.")