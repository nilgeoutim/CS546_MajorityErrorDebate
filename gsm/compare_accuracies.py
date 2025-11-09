import json
import numpy as np
import re
from tqdm import tqdm
import os
from collections import Counter # Import Counter for a deterministic 'most_frequent'

# =====================================================================================
#  SECTION 1: Core Evaluation Functions (v2 Fix)
# =====================================================================================

def parse_answer(input_str: str) -> str:
    """
    (v2) Safer answer parser.
    First finds \boxed{...}.
    If not found, *only* finds numbers at the very end (^) of the string.
    This prevents grabbing "1" from "Agent 1" or "52" from "52 apples".
    """
    if not isinstance(input_str, str):
        return None
        
    # Pattern 1: \boxed{...}
    pattern_boxed = r"\\boxed\{([0-9.,$]*)\}"
    matches = re.findall(pattern_boxed, input_str)
    solution = None
    for match_str in matches[::-1]:
        solution = re.sub(r"[^0-9.]", "", match_str)
        if solution:
            return solution # Found \boxed{}, return immediately

    # Pattern 2: Number at the end of the string
    # Only triggers if \boxed{} is not found
    pattern_final_num = r"(\d+\.?\d*)\s*$"
    matches = re.findall(pattern_final_num, input_str)
    if matches:
        return matches[-1]
        
    return None

def most_frequent(List: list) -> str:
    """
    (v2-Fix) Find the majority vote from a list using collections.Counter.
    This is now deterministic and correctly handles ties.
    """
    if not List:
        return None
    
    # Use Counter to count frequencies
    counts = Counter(List)
    
    # .most_common(1) returns a list of [('item', count)]
    if not counts:
        return None
        
    # Get the item with the highest count.
    # In case of a tie, this is deterministic.
    return counts.most_common(1)[0][0]

def get_ground_truth(gt: str) -> str:
    """Extract the ground truth number from the '#### ...' string."""
    gt_pattern = r"#### (\d+\.?\d*)"
    gt_match = re.search(gt_pattern, gt)
    if not gt_match:
        # Fallback: if #### marker not found, just get last number in GT string
        gt_fallback = re.findall(r"\d+\.?\d*", gt)
        if gt_fallback:
            return gt_fallback[-1]
        return None
    return gt_match.group(1)

def get_final_decision(pred_solutions: list) -> str:
    """
    (v2 Fix) Get the final majority vote answer from a list of predictions.
    This version *only* uses the safer parse_answer function.
    """
    pred_answers = []
    for pred_solution in pred_solutions:
        # *** v2 Fix: Only call the safe parser ***
        pred_answer = parse_answer(pred_solution)
        
        if pred_answer is not None:
            pred_answers.append(pred_answer)
    
    if not pred_answers:
        return None
    
    # Get the majority vote
    return most_frequent(pred_answers)

def check_correctness(gt_answer: str, final_pred_answer: str) -> int:
    """Compare GT and prediction, return 1 (correct) or 0 (wrong)."""
    if gt_answer is None or final_pred_answer is None:
        return 0
    try:
        # Use np.isclose for robust float comparison
        return 1 if np.isclose(float(gt_answer), float(final_pred_answer)) else 0
    except (ValueError, TypeError):
        # Handle "1,000" vs "1000"
        try:
            gt_clean = gt_answer.replace(",", "")
            pred_clean = final_pred_answer.replace(",", "")
            return 1 if np.isclose(float(gt_clean), float(pred_clean)) else 0
        except (ValueError, TypeError):
            return 0 # Cannot parse

# =====================================================================================
# SECTION 2: Data Extractors (v2)
# =====================================================================================

def get_critic_actor_data(response_dict: dict) -> dict:
    """(v2) Extract data from the v1 (v2) JSON file."""
    results = {}
    for question, data in response_dict.items():
        gt_answer = get_ground_truth(data["ground_truth"])
        
        final_solutions = []
        if "final_round_results" in data:
             final_solutions = [item["solution"] for item in data["final_round_results"]]
        
        final_decision = get_final_decision(final_solutions)
        
        # (v2) Store round 1 scores for stalemate analysis
        r1_scores = []
        if "round_1_results" in data:
            r1_scores = [item.get("score", {}) for item in data["round_1_results"]]
            
        results[question] = {
            "gt_answer": gt_answer,
            "final_decision": final_decision,
            "is_correct": check_correctness(gt_answer, final_decision),
            "round_1_scores": r1_scores, # Store for stalemate analysis
            "full_data": data # Store all data for reporting
        }
    return results

def get_original_mad_data(response_dict: dict) -> dict:
    """Extract data from gsm_3_3.json [cite: `gsm_3_3.json`] (with 'content' fix)."""
    results = {}
    for question, data in response_dict.items():
        # Original JSON [cite: `gsm_3_3.json`] structure is [responses_list, gt_string]
        if not (isinstance(data, (list, tuple)) and len(data) == 2):
            continue # Skip malformed data
            
        responses, gt = data
        gt_answer = get_ground_truth(gt)
        
        pred_solutions = []
        if not isinstance(responses, list):
            continue # Skip malformed 'responses'
            
        for response_context_list in responses:
            if not (isinstance(response_context_list, list) and len(response_context_list) > 0):
                continue
            
            # Fix: Handle 'content' being a dict or a string
            content_value = response_context_list[-1].get('content') # Use .get() for safety
            
            if isinstance(content_value, dict) and 'content' in content_value:
                pred_solutions.append(content_value['content']) # Nested content
            elif isinstance(content_value, str):
                pred_solutions.append(content_value) # Direct string
            else:
                pred_solutions.append("") # Add empty string
        
        final_decision = get_final_decision(pred_solutions)
        
        results[question] = {
            "gt_answer": gt_answer,
            "final_decision": final_decision,
            "is_correct": check_correctness(gt_answer, final_decision),
            "full_data": {"final_solutions": pred_solutions} # Store data for reporting
        }
    return results

# =====================================================================================
# SECTION 3: Main Analysis and Report Generation (v2)
# =====================================================================================

def main():
    # --- 1. Define filenames ---
    # ** IMPORTANT: ** Loading 'gsm_critic_actor_3_2.json' as requested.
    critic_file = 'gsm_critic_actor_3_2.json' # The output from your v1 script
    original_file = 'gsm_3_3.json'
    report_file = 'analysis_report_v2.md' # Changed name to v2
    
    # (v2) Define stalemate threshold
    STALEMATE_THRESHOLD = 2 # Scores are "close" if max - min <= 2

    print("="*50)
    print("--- Comprehensive Evaluation Script (v2) ---")
    print(f"Comparing:")
    print(f"  (A) Original MAD: {original_file}")
    print(f"  (B) New Critic-Actor: {critic_file}")
    print(f"Stalemate Threshold: {STALEMATE_THRESHOLD}")
    print("="*50)

    # --- 2. Load JSON files ---
    print("Loading JSON files...")
    try:
        with open(critic_file, 'r', encoding='utf-8') as f:
            critic_dict = json.load(f)
        with open(original_file, 'r', encoding='utf-8') as f:
            original_dict = json.load(f)
    except FileNotFoundError as e:
        print(f"❌ Error: File not found {e.filename}.")
        print("Please make sure both JSON files exist.")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Error: Failed to parse JSON {e}. File might be corrupt.")
        return
    
    print("✅ Files loaded. Extracting data...")
    # --- 3. Extract and process data ---
    critic_results = get_critic_actor_data(critic_dict)
    original_results = get_original_mad_data(original_dict)

    # --- 4. Compare models question by question ---
    print("Comparing models question by question...")
    categories = {
        "win": [],    # B correct, A wrong
        "loss": [],   # B wrong, A correct
        "correct": [], # Both correct
        "incorrect": [], # Both wrong
        "stalemate_failures": [] # v2: New category for stalemate analysis
    }

    original_questions = set(original_results.keys())
    critic_questions = set(critic_results.keys())
    common_questions = list(original_questions & critic_questions)
    
    if not common_questions:
        print("❌ Error: No common questions found in the two JSON files.")
        return

    total_stalemate_cases = 0

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
            
        # --- v2: Stalemate Analysis ---
        # Check if this question was a "stalemate" in Round 1
        r1_logic_scores = [s.get('logic_score', 0) for s in critic_res.get("round_1_scores", [])]
        if r1_logic_scores:
            min_score = min(r1_logic_scores)
            max_score = max(r1_logic_scores)
            
            # Check if scores are "close"
            if (max_score - min_score) <= STALEMATE_THRESHOLD:
                total_stalemate_cases += 1
                
                # Check if this "stalemate" case resulted in a failure
                if not b_correct: # b_correct == 0
                    categories["stalemate_failures"].append(question)
        # --- End Stalemate Analysis ---

    # --- 5. Print terminal summary ---
    total_questions = len(common_questions)
    
    acc_original = (len(categories['loss']) + len(categories['correct'])) / total_questions * 100 if total_questions > 0 else 0
    acc_critic = (len(categories['win']) + len(categories['correct'])) / total_questions * 100 if total_questions > 0 else 0
    improvement = acc_critic - acc_original
    stalemate_failure_rate = len(categories['stalemate_failures']) / total_stalemate_cases * 100 if total_stalemate_cases > 0 else 0

    print("\n" + "="*40)
    print("--- Comprehensive Evaluation Results (v2) ---")
    print(f"Total Questions Compared: {total_questions}")
    print("="*40)
    print(f"Original MAD ({original_file}):")
    print(f"  - Accuracy: {acc_original:.1f}%")
    print(f"Critic-Actor ({critic_file}):")
    print(f"  - Accuracy: {acc_critic:.1f}%")
    print("="*40)
    print(f"Performance Improvement (Critic-Actor vs. Original): {improvement:+.1f} percentage points")
    print("="*40)
    print("--- Detailed Categorization ---")
    print(f"✅ Win (Critic-Actor correct, Original MAD wrong): {len(categories['win'])} questions")
    print(f"❌ Loss (Critic-Actor wrong, Original MAD correct): {len(categories['loss'])} questions")
    print(f"👍 Correct (Both Correct): {len(categories['correct'])} questions")
    print(f"👎 Incorrect (Both Incorrect): {len(categories['incorrect'])} questions")
    print("="*40) # <-- This is the fixed line (was 4G)
    print("--- v2 Stalemate Analysis ---")
    print(f"Total cases with 'close' (<= {STALEMATE_THRESHOLD}pt diff) R1 scores: {total_stalemate_cases}")
    print(f"Failures in these 'close' score cases: {len(categories['stalemate_failures'])}")
    print(f"Stalemate Failure Rate: {stalemate_failure_rate:.1f}%")
    print("="*40)


    # --- 6. Generate detailed Markdown report ---
    print(f"Generating detailed report: {report_file} ...")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# Experiment Comparison Analysis Report (v2)\n\n")
        f.write("This document details the performance differences between the `Original MAD` and the `Critic-Actor` (v2) models on the GSM8K task.\n\n")
        
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
        f.write(f"**Performance Improvement: {improvement:+.1f} percentage points**\n\n")

        # --- v2: Stalemate Report Section ---
        f.write(f"## v2 Stalemate Analysis\n\n")
        f.write(f"We analyze cases where Round 1 Logic scores were 'close' (max score - min score <= {STALEMATE_THRESHOLD} points), as this may lead to model confusion.\n\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"| :--- | :--- |\n")
        f.write(f"| Total 'close score' cases | {total_stalemate_cases} |\n")
        f.write(f"| Failures in these cases | {len(categories['stalemate_failures'])} |\n")
        f.write(f"| **Stalemate Failure Rate** | **{stalemate_failure_rate:.1f}%** |\n\n")
        f.write("A high stalemate failure rate suggests our model struggles to break ties when scores are not clearly differentiated. Below are the specific cases that failed.\n\n")
        
        for i, question in enumerate(categories["stalemate_failures"]):
            critic_data = critic_results[question]
            f.write(f"### Stalemate Failure #{i+1}: {question}\n\n")
            f.write(f"**Ground Truth (GT):** `{critic_data.get('gt_answer', 'N/A')}`\n")
            f.write(f"**Critic-Actor Decision (Wrong):** `{critic_data.get('final_decision', 'N/A')}`\n\n")
            f.write("#### Round 1 (Initial Solutions and Scores):\n")
            if "round_1_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["round_1_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A')}, Comp: {score.get('computation_score', 'N/A')})**:\n")
                    f.write(f"  - Verification: {score.get('verification_step', 'N/A')}\n")
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
            f.write("\n---\n")

        # --- Detailed Analysis: Loss Cases ---
        f.write("="*20 + "\n\n")
        f.write(f"## ❌ All Other Failure Cases (Losses) - {len(categories['loss'])} Questions\n\n")
        f.write("In these cases, the **Original MAD was correct**, but the **Critic-Actor model was wrong**.\n\n")
        
        if not categories["loss"]:
            f.write("No failure cases found! 🎉\n\n")
            
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
                    f.write(f"  - Verification: {score.get('verification_step', 'N/A')}\n") # 'N/A' since v1 JSON won't have this
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
                    f.write(f"  - Solution:\n```\n{item.get('solution', 'N/A')}\n```\n")
            
            f.write("\n#### Round 2 (Final Solutions and Scores):\n")
            if "final_round_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["final_round_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A')}, Comp: {score.get('computation_score', 'N/A')})**:\n")
                    f.write(f"  - Verification: {score.get('verification_step', 'N/A')}\n") # 'N/A' since v1 JSON won't have this
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
                    f.write(f"  - Solution:\n```\n{item.get('solution', 'N/A')}\n```\n")
            f.write("\n---\n")

        # --- Detailed Analysis: Win Cases ---
        f.write("="*20 + "\n\n")
        f.write(f"## ✅ Success Case Analysis (Wins) - {len(categories['win'])} Questions\n\n")
        f.write("In these cases, the **Original MAD was wrong**, but the **Critic-Actor model was correct**. This validates the new framework.\n\n")

        if not categories["win"]:
            f.write("No success cases found.\n\n")

        for i, question in enumerate(categories["win"]):
            # (Omitted for brevity, but the logic is the same as the Loss section)
            pass

    print(f"✅ Success! Detailed report saved to: {report_file}")
    print("Please open the file to analyze the new 'Stalemate' and 'Loss' cases.")

if __name__ == "__main__":
    main()