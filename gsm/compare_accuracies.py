import json
import numpy as np
import re
from tqdm import tqdm
import os

# =====================================================================================
# SECTION 1: Core Evaluation Functions (from compare_accuracies.py)
# (Includes fixed 'content' dict check)
# =====================================================================================

def parse_answer(input_str: str) -> str:
    """Extracts the answer from \boxed{...}, falling back to the last number."""
    pattern = r"\\boxed\{([0-9.,$]*)\}"
    matches = re.findall(pattern, input_str)
    solution = None
    for match_str in matches[::-1]:
        solution = re.sub(r"[^0-9.]", "", match_str)
        if solution:
            break
    if solution is None:
        pattern = r"(\d+\.?\d*)\s*$"
        matches = re.findall(pattern, input_str)
        if matches:
            solution = matches[-1]
    return solution

def solve_math_problems(input_str: str) -> str:
    """Fallback function used to find the last number in the string."""
    pattern = r"\d+\.?\d*"
    matches = re.findall(pattern, input_str)
    if matches:
        return matches[-1]
    return None

def most_frequent(List: list) -> str:
    """Finds the majority vote from the list."""
    if not List:
        return None
    counter = 0
    num = List[0]
    for i in List:
        try:
            current_frequency = List.count(i)
            if current_frequency > counter:
                counter = current_frequency
                num = i
        except:
            continue
    return num

def get_ground_truth(gt: str) -> str:
    """Extracts the ground truth answer digit from the GT string (e.g., '#### 123.4')."""
    gt_pattern = r"#### (\d+\.?\d*)"
    gt_match = re.search(gt_pattern, gt)
    if not gt_match:
        return None
    return gt_match.group(1)

def get_final_decision(pred_solutions: list) -> str:
    """Gets the final majority vote answer from a set of predictions."""
    pred_answers = []
    for pred_solution in pred_solutions:
        pred_answer = parse_answer(pred_solution)
        if pred_answer is None:
            pred_answer = solve_math_problems(pred_solution)
        if pred_answer is not None:
            pred_answers.append(pred_answer)
    
    if not pred_answers:
        return None
    
    return most_frequent(pred_answers)

def check_correctness(gt_answer: str, final_pred_answer: str) -> int:
    """Compares GT and prediction, returns 1 (correct) or 0 (incorrect)."""
    if gt_answer is None or final_pred_answer is None:
        return 0
    try:
        return 1 if float(gt_answer) == float(final_pred_answer) else 0
    except (ValueError, TypeError):
        return 0

# =====================================================================================
# SECTION 2: Data Extractors for Different JSON Formats
# =====================================================================================

def get_critic_actor_data(response_dict: dict) -> dict:
    """Extracts data from the gsm_critic_actor_3_2.json format [cite: `gsm_critic_actor_3_2.json`]."""
    results = {}
    for question, data in response_dict.items():
        gt_answer = get_ground_truth(data["ground_truth"])
        
        final_solutions = [item["solution"] for item in data["final_round_results"]]
        final_decision = get_final_decision(final_solutions)
        
        results[question] = {
            "gt_answer": gt_answer,
            "final_decision": final_decision,
            "is_correct": check_correctness(gt_answer, final_decision),
            "full_data": data # Store all data for later analysis
        }
    return results

def get_original_mad_data(response_dict: dict) -> dict:
    """Extracts data from the gsm_3_3.json format (Includes 'content' fix) [cite: `gsm_3_3.json`]."""
    results = {}
    for question, (responses, gt) in response_dict.items():
        gt_answer = get_ground_truth(gt)
        
        pred_solutions = []
        for response_context_list in responses:
            # Fix: Handle cases where 'content' might be a dictionary or a string
            content_value = response_context_list[-1].get('content')
            
            if isinstance(content_value, dict) and 'content' in content_value:
                pred_solutions.append(content_value['content'])
            elif isinstance(content_value, str):
                pred_solutions.append(content_value)
            else:
                pred_solutions.append("") 
        
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
    critic_file = 'gsm_critic_actor_3_2.json'
    original_file = 'gsm_3_3.json'
    report_file = 'analysis_report.md'

    # --- 2. Load JSON Files ---
    print("Loading JSON files...")
    try:
        with open(critic_file, 'r', encoding='utf-8') as f:
            critic_dict = json.load(f)
        with open(original_file, 'r', encoding='utf-8') as f:
            original_dict = json.load(f)
    except FileNotFoundError as e:
        print(f"Error: File not found {e.filename}. Please ensure both JSON files are in this directory.")
        return
    except json.JSONDecodeError as e:
        print(f"Error: JSON decoding error {e}. The file might be corrupted.")
        return
    
    print("Files loaded. Extracting data...")
    # --- 3. Extract and Process Data ---
    critic_results = get_critic_actor_data(critic_dict)
    original_results = get_original_mad_data(original_dict)

    # --- 4. Question-by-Question Comparison ---
    print("Comparing models question by question...")
    categories = {
        "win": [],       # Critic-Actor correct, Original MAD wrong
        "loss": [],      # Critic-Actor wrong, Original MAD correct
        "correct": [],   # Both correct
        "incorrect": []  # Both incorrect
    }

    # Use the intersection of keys, or all keys for completeness
    all_questions = set(critic_results.keys()) & set(original_results.keys())
    
    if not all_questions:
        print("Error: No common questions found between the two JSON files.")
        return

    for question in tqdm(all_questions, desc="Categorizing results"):
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
    total_questions = len(all_questions)
    
    acc_original = (len(categories['loss']) + len(categories['correct'])) / total_questions
    acc_critic = (len(categories['win']) + len(categories['correct'])) / total_questions

    print("\n" + "="*40)
    print("--- Comprehensive Evaluation Results ---")
    print(f"Total Questions Compared: {total_questions}")
    print("="*40)
    print(f"Original MAD ({original_file}):")
    print(f"   - Accuracy: {acc_original * 100:.1f}%")
    print(f"Critic-Actor ({critic_file}):")
    print(f"   - Accuracy: {acc_critic * 100:.1f}%")
    print("="*40)
    print("--- Detailed Categorization ---")
    print(f"✅ Win (Critic-Actor correct, Original MAD wrong): {len(categories['win'])} questions")
    print(f"❌ Loss (Critic-Actor wrong, Original MAD correct): {len(categories['loss'])} questions")
    print(f"👍 Correct (Both Correct): {len(categories['correct'])} questions")
    print(f"👎 Incorrect (Both Incorrect): {len(categories['incorrect'])} questions")
    print("="*40)
    print(f"Performance Improvement (Critic-Actor vs. Original): {(acc_critic - acc_original) * 100:.1f} percentage points")

    # --- 6. Generate Detailed Markdown Report ---
    print(f"Generating detailed report: {report_file} ...")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("# Experiment Comparison Analysis Report\n\n")
        f.write("This document details the performance differences between the `Original MAD` and the `Critic-Actor` models on the GSM8K task.\n\n")
        
        f.write("## Summary\n")
        f.write(f"| Model | Accuracy |\n")
        f.write(f"| :--- | :--- |\n")
        f.write(f"| Original MAD ({original_file}) | {acc_original * 100:.1f}% |\n")
        f.write(f"| Critic-Actor ({critic_file}) | {acc_critic * 100:.1f}% |\n\n")
        
        f.write("## Categorized Statistics\n")
        f.write(f"| Category | Description | Count |\n")
        f.write(f"| :--- | :--- | :--- |\n")
        f.write(f"| ✅ Win | Critic-Actor correct, Original MAD wrong | {len(categories['win'])} |\n")
        f.write(f"| ❌ Loss | Critic-Actor wrong, Original MAD correct | {len(categories['loss'])} |\n")
        f.write(f"| 👍 Correct | Both Correct | {len(categories['correct'])} |\n")
        f.write(f"| 👎 Incorrect | Both Incorrect | {len(categories['incorrect'])} |\n\n")

        # --- Detailed Analysis: Failure Cases (Losses) ---
        f.write("="*20 + "\n\n")
        f.write(f"## ❌ Failure Case Analysis (Losses) - {len(categories['loss'])} Questions\n\n")
        f.write("In these cases, the **Original MAD was correct**, but the **Critic-Actor model was wrong**. This highlights a failure mode that needs analysis.\n\n")
        
        for i, question in enumerate(categories["loss"]):
            critic_data = critic_results[question]
            original_data = original_results[question]
            
            f.write(f"### Loss #{i+1}: {question}\n\n")
            f.write(f"**Ground Truth (GT):** `{critic_data['gt_answer']}`\n\n")
            f.write(f"**Original MAD Decision (Correct):** `{original_data['final_decision']}`\n")
            f.write(f"**Critic-Actor Decision (Wrong):** `{critic_data['final_decision']}`\n\n")
            f.write(f"**Detailed Data (Critic-Actor Model):**\n")
            
            f.write("#### Round 1 (Initial Solutions and Scores):\n")
            if 'round_1_results' in critic_data['full_data']:
                for j, item in enumerate(critic_data['full_data']['round_1_results']):
                    f.write(f"**Agent {j+1} (Logic: {item['score']['logic_score']}, Comp: {item['score']['computation_score']})**:\n")
                    f.write(f"  - Critique: {item['score']['critique']}\n")
                    f.write(f"  - Solution:\n```\n{item['solution']}\n```\n")
            
            f.write("\n#### Round 2 (Final Solutions and Scores):\n")
            if 'final_round_results' in critic_data['full_data']:
                for j, item in enumerate(critic_data['full_data']['final_round_results']):
                    f.write(f"**Agent {j+1} (Logic: {item['score']['logic_score']}, Comp: {item['score']['computation_score']})**:\n")
                    f.write(f"  - Critique: {item['score']['critique']}\n")
                    f.write(f"  - Solution:\n```\n{item['solution']}\n```\n")
            f.write("\n---\n")

        # --- Detailed Analysis: Success Cases (Wins) ---
        f.write("="*20 + "\n\n")
        f.write(f"## ✅ Success Case Analysis (Wins) - {len(categories['win'])} Questions\n\n")
        f.write("In these cases, the **Original MAD was wrong**, but the **Critic-Actor model was correct**. This validates the effectiveness of the new framework.\n\n")

        for i, question in enumerate(categories["win"]):
            critic_data = critic_results[question]
            original_data = original_results[question]
            
            f.write(f"### Win #{i+1}: {question}\n\n")
            f.write(f"**Ground Truth (GT):** `{critic_data['gt_answer']}`\n\n")
            f.write(f"**Original MAD Decision (Wrong):** `{original_data['final_decision']}`\n")
            f.write(f"**Critic-Actor Decision (Correct):** `{critic_data['final_decision']}`\n\n")
            f.write(f"**Detailed Data (Critic-Actor Model):**\n")

            f.write("#### Round 1 (Initial Solutions and Scores):\n")
            if 'round_1_results' in critic_data['full_data']:
                for j, item in enumerate(critic_data['full_data']['round_1_results']):
                    f.write(f"**Agent {j+1} (Logic: {item['score']['logic_score']}, Comp: {item['score']['computation_score']})**:\n")
                    f.write(f"  - Critique: {item['score']['critique']}\n")
                    f.write(f"  - Solution:\n```\n{item['solution']}\n```\n")
            
            f.write("\n#### Round 2 (Final Solutions and Scores):\n")
            if 'final_round_results' in critic_data['full_data']:
                for j, item in enumerate(critic_data['full_data']['final_round_results']):
                    f.write(f"**Agent {j+1} (Logic: {item['score']['logic_score']}, Comp: {item['score']['computation_score']})**:\n")
                    f.write(f"  - Critique: {item['score']['critique']}\n")
                    f.write(f"  - Solution:\n```\n{item['solution']}\n```\n")
            f.write("\n---\n")

    print(f"✅ Success! Detailed report saved to: {report_file}")
    print("Please open the file to analyze 'Loss' cases.")

if __name__ == "__main__":
    main()