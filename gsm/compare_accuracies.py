import json
import re
import os
from collections import Counter
import numpy as np
from tqdm import tqdm

# =====================================================================================
# SECTION 1: Helper Functions
# =====================================================================================

def parse_answer(solution_text: str) -> str:
    """
    Extracts the answer from the solution text.
    Expects the answer to be in the format '#### [answer]'.
    """
    if not solution_text:
        return None
    
    # Look for the standard GSM8K delimiter
    match = re.search(r"####\s*(.+)", solution_text)
    if match:
        return match.group(1).strip()
    
    # Fallback: look for the last number in the text
    # This is less reliable but useful if the model forgets the delimiter
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", solution_text)
    if numbers:
        return numbers[-1]
        
    return None

def most_frequent(List: list) -> str:
    """Deterministic majority vote using Counter."""
    if not List:
        return None
    counts = Counter(List)
    if not counts:
        return None
    # Get the most common item. In case of a tie, Counter returns one of them.
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
    """Get the final majority vote answer."""
    pred_answers = []
    for pred_solution in pred_solutions:
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

def read_jsonl(path: str) -> list:
    """Reads a JSONL file."""
    with open(path, 'r', encoding='utf-8') as fh:
        return [json.loads(line) for line in fh.readlines() if line]

# =====================================================================================
# SECTION 2: Data Extractors
# =====================================================================================

def _safe_parse_float_from_data(value: any, default: float = 0.0) -> float:
    """Robustly convert a value *from the loaded JSON* to float."""
    try:
        return float(value)
    except (ValueError, TypeError, NameError): # NameError for safety
        return default

def get_critic_actor_data(response_dict: dict) -> dict:
    """Extract data from the JSON file (handles floats)."""
    results = {}
    for question, data in response_dict.items():
        gt_answer = get_ground_truth(data["ground_truth"])
        
        final_solutions = []
        if "final_round_results" in data:
             final_solutions = [item["solution"] for item in data["final_round_results"]]
        
        final_decision = get_final_decision(final_solutions)
        
        # Store round 1 scores (now floats)
        r1_scores = []
        if "round_1_results" in data:
            for item in data["round_1_results"]:
                score_dict = item.get("score", {})
                r1_scores.append({
                    "logic_score": _safe_parse_float_from_data(score_dict.get("logic_score")),
                    "computation_score": _safe_parse_float_from_data(score_dict.get("computation_score"))
                })
            
        results[question] = {
            "gt_answer": gt_answer,
            "final_decision": final_decision,
            "is_correct": check_correctness(gt_answer, final_decision),
            "round_1_scores": r1_scores, # Store for stalemate analysis
            "full_data": data # Store all data for reporting
        }
    return results

def get_majority_error_data(data_list: list) -> dict:
    """Extract data from gsm_majority_error.jsonl."""
    results = {}
    for item in data_list:
        question = item.get('question')
        gt_str = item.get('answer')
        gt_answer = get_ground_truth(gt_str)
        
        # For majority error dataset, we assume the "original" model failed.
        # We don't have the original wrong answer, so we set final_decision to None
        # to ensure it counts as incorrect.
        final_decision = None 
        
        results[question] = {
            "gt_answer": gt_answer,
            "final_decision": final_decision,
            "is_correct": 0, # Always wrong for this dataset
            "full_data": item
        }
    return results

# =====================================================================================
# SECTION 3: Main Analysis and Report Generation
# =====================================================================================

def main():
    # --- 1. Define filenames ---
    critic_file = 'gsm/gsm_critic_actor_3_7.json' 
    original_file = 'gsm/gsm_majority_error.jsonl'
    report_file = 'gsm/analysis_report_3_7_majority_error.md'
    
    STALEMATE_THRESHOLD = 2.0 # Scores are "close" if max - min <= 2.0

    print("="*50)
    print("--- Comprehensive Evaluation Script (Majority Error) ---")
    print("Loading files...")
    
    try:
        with open(critic_file, 'r', encoding='utf-8') as f:
            critic_dict = json.load(f)
        
        # Load original file as JSONL
        original_list = read_jsonl(original_file)
        
    except FileNotFoundError as e:
        print(f"Error: File not found {e.filename}.")
        return
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON {e}. File might be corrupt.")
        return
    
    print("Files loaded. Extracting data...")
    # --- 3. Extract and process data ---
    critic_results = get_critic_actor_data(critic_dict)
    original_results = get_majority_error_data(original_list)

    # --- 4. Compare models question by question ---
    print("Comparing models question by question...")
    categories = {
        "win": [],    # B correct, A wrong
        "loss": [],   # B wrong, A correct
        "correct": [], # Both correct
        "incorrect": [], # Both wrong
        "stalemate_failures": [] # Stalemate analysis
    }

    original_questions = set(original_results.keys())
    critic_questions = set(critic_results.keys())
    common_questions = list(original_questions & critic_questions)
    
    if not common_questions:
        print("Error: No common questions found in the two files.")
        print(f"Original questions: {len(original_questions)}")
        print(f"Critic questions: {len(critic_questions)}")
        return

    total_stalemate_cases = 0

    for question in tqdm(common_questions, desc="Categorizing results"):
        critic_res = critic_results[question]
        original_res = original_results[question]

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
            
        # --- Stalemate Analysis ---
        r1_logic_scores = [s.get('logic_score', 0.0) for s in critic_res.get("round_1_scores", [])]
        if r1_logic_scores:
            min_score = min(r1_logic_scores)
            max_score = max(r1_logic_scores)
            
            # Check if scores are "close"
            if (max_score - min_score) <= STALEMATE_THRESHOLD:
                total_stalemate_cases += 1
                
    # --- 5. Print terminal summary ---
    total_questions = len(common_questions)
    
    # Calculate accuracy
    acc_original = (len(categories['loss']) + len(categories['correct'])) / total_questions * 100 if total_questions > 0 else 0
    acc_critic = (len(categories['win']) + len(categories['correct'])) / total_questions * 100 if total_questions > 0 else 0
    improvement = acc_critic - acc_original
    stalemate_failure_rate = len(categories['stalemate_failures']) / total_stalemate_cases * 100 if total_stalemate_cases > 0 else 0

    print("\n" + "="*40)
    print("--- Evaluation Results ---")
    print(f"Total Questions Compared: {total_questions}")
    print("="*40)
    print(f"Original (Majority Error Baseline):")
    print(f"  - Accuracy: {acc_original:.1f}%")
    print(f"Critic-Actor (New Model):")
    print(f"  - Accuracy: {acc_critic:.1f}%")
    print("="*40)
    print(f"Performance Improvement: {improvement:+.1f} percentage points")
    print("="*40)
    print("--- Detailed Categorization ---")
    print(f"Win (New Correct, Old Wrong): {len(categories['win'])}")
    print(f"Loss (New Wrong, Old Correct): {len(categories['loss'])}")
    print(f"Correct (Both Correct): {len(categories['correct'])}")
    print(f"Incorrect (Both Incorrect): {len(categories['incorrect'])}")
    print("="*40)
    print("--- Stalemate Analysis ---")
    print(f"Total cases with 'close' (<= {STALEMATE_THRESHOLD}pt diff) R1 scores: {total_stalemate_cases}")
    print(f"Failures in these 'close' score cases: {len(categories['stalemate_failures'])}")
    print(f"Stalemate Failure Rate: {stalemate_failure_rate:.1f}%")
    print("="*40)

    # --- 6. Weighted Voting Simulation (Risk/Reward Analysis) ---
    print("\n" + "="*40)
    print("--- Weighted Voting Simulation (Risk/Reward) ---")
    
    fixed_cases = []   # Majority Wrong -> Weighted Correct (GAIN)
    broken_cases = []  # Majority Correct -> Weighted Wrong (LOSS)
    
    # Calibration Stats
    correct_confidences = []
    incorrect_confidences = []

    for question in common_questions:
        data = critic_results[question]
        gt_answer = data['gt_answer']
        majority_decision = data['final_decision']
        
        # Get weighted decision
        final_round_results = data['full_data'].get('final_round_results', [])
        
        # Aggregate scores by answer
        answer_scores = {}
        
        for item in final_round_results:
            sol = item.get('solution', '')
            ans = parse_answer(sol)
            if ans is None: continue
            
            score = item.get('score', {})
            logic = _safe_parse_float_from_data(score.get('logic_score'))
            comp = _safe_parse_float_from_data(score.get('computation_score'))
            total_weight = logic + comp # Simple sum weighting
            
            if ans not in answer_scores:
                answer_scores[ans] = 0.0
            answer_scores[ans] += total_weight
            
            # Calibration tracking
            # We want to check if the *individual agent's* answer is correct
            is_ans_correct = check_correctness(gt_answer, ans)
            if is_ans_correct:
                correct_confidences.append(total_weight)
            else:
                incorrect_confidences.append(total_weight)

        # Find best weighted answer
        weighted_decision = None
        if answer_scores:
            weighted_decision = max(answer_scores, key=answer_scores.get)
            
        # Compare outcomes
        majority_correct = check_correctness(gt_answer, majority_decision)
        weighted_correct = check_correctness(gt_answer, weighted_decision)
        
        if not majority_correct and weighted_correct:
            fixed_cases.append(question)
        elif majority_correct and not weighted_correct:
            broken_cases.append(question)

    print(f"GAIN (Fixed): {len(fixed_cases)} cases")
    print(f"LOSS (Broken): {len(broken_cases)} cases")
    print(f"Net Improvement: {len(fixed_cases) - len(broken_cases)} cases")
    
    # Calibration Report
    avg_correct_conf = sum(correct_confidences)/len(correct_confidences) if correct_confidences else 0
    avg_incorrect_conf = sum(incorrect_confidences)/len(incorrect_confidences) if incorrect_confidences else 0
    
    print("\n--- Calibration Analysis ---")
    print(f"Avg Confidence (Logic+Comp) for CORRECT answers:   {avg_correct_conf:.2f} / 20.0")
    print(f"Avg Confidence (Logic+Comp) for INCORRECT answers: {avg_incorrect_conf:.2f} / 20.0")
    print(f"Delta (Signal Strength): {avg_correct_conf - avg_incorrect_conf:.2f}")
    print("="*40)


    # --- 7. Generate detailed Markdown report ---
    print(f"Generating detailed report: {report_file} ...")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# Experiment Analysis Report: Majority Error Dataset\n\n")
        f.write("This document details the performance of the `Critic-Actor` model on 100 difficult questions from `gsm_majority_error.jsonl`.\n\n")
        
        f.write("## Summary\n")
        f.write(f"| Model | Accuracy |\n")
        f.write(f"| :--- | :--- |\n")
        f.write(f"| Original Baseline | {acc_original:.1f}% |\n")
        f.write(f"| Critic-Actor (New) | {acc_critic:.1f}% |\n\n")
        
        f.write("## Categorized Statistics\n")
        f.write(f"| Category | Description | Count |\n")
        f.write(f"| :--- | :--- | :--- |\n")
        f.write(f"| Win | Critic-Actor correct | {len(categories['win'])} |\n")
        f.write(f"| Incorrect | Critic-Actor incorrect | {len(categories['incorrect'])} |\n\n")
        f.write(f"**Performance Improvement: {improvement:+.1f} percentage points**\n\n")

        # --- Stalemate Report Section ---
        f.write(f"## Stalemate Analysis\n\n")
        f.write(f"We analyze cases where Round 1 Logic scores were 'close' (max score - min score <= {STALEMATE_THRESHOLD} points).\n\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"| :--- | :--- |\n")
        f.write(f"| Total 'close score' cases | {total_stalemate_cases} |\n")
        f.write(f"| Failures in these cases | {len(categories['stalemate_failures'])} |\n")
        f.write(f"| **Stalemate Failure Rate** | **{stalemate_failure_rate:.1f}%** |\n\n")
        
        # --- Detailed Analysis: Win Cases ---
        f.write("="*20 + "\n\n")
        f.write(f"## Success Cases (Wins) - {len(categories['win'])} Questions\n\n")
        f.write("In these cases, the Critic-Actor model correctly solved the difficult problem.\n\n")

        if not categories["win"]:
            f.write("No success cases found.\n\n")

        for i, question in enumerate(categories["win"]):
            critic_data = critic_results[question]
            
            f.write(f"### Win #{i+1}: {question}\n\n")
            f.write(f"**Ground Truth (GT):** `{critic_data.get('gt_answer', 'N/A')}`\n")
            f.write(f"**Critic-Actor Decision:** `{critic_data.get('final_decision', 'N/A')}`\n\n")
            
            f.write("#### Round 1 (Initial Solutions and Scores):\n")
            if "round_1_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["round_1_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A'):.1f}, Comp: {score.get('computation_score', 'N/A'):.1f})**:\n")
                    f.write(f"  - Verification: {score.get('verification_step', 'N/A')}\n")
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
                    f.write(f"  - Solution:\n```\n{item.get('solution', 'N/A')}\n```\n")
            
            f.write("\n#### Round 2 (Final Solutions and Scores):\n")
            if "final_round_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["final_round_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A'):.1f}, Comp: {score.get('computation_score', 'N/A'):.1f})**:\n")
                    f.write(f"  - Verification: {score.get('verification_step', 'N/A')}\n")
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
                    f.write(f"  - Solution:\n```\n{item.get('solution', 'N/A')}\n```\n")
            f.write("\n---\n")

        # --- Detailed Analysis: Incorrect Cases ---
        f.write("="*20 + "\n\n")
        f.write(f"## Failure Cases (Incorrect) - {len(categories['incorrect'])} Questions\n\n")
        f.write("In these cases, the Critic-Actor model failed to solve the problem.\n\n")
        
        if not categories["incorrect"]:
            f.write("No failure cases found!\n\n")
            
        for i, question in enumerate(categories["incorrect"]):
            critic_data = critic_results[question]
            
            f.write(f"### Failure #{i+1}: {question}\n\n")
            f.write(f"**Ground Truth (GT):** `{critic_data.get('gt_answer', 'N/A')}`\n")
            f.write(f"**Critic-Actor Decision:** `{critic_data.get('final_decision', 'N/A')}`\n\n")
            f.write(f"**Detailed Data (Critic-Actor Model):**\n")
            
            f.write("#### Round 1 (Initial Solutions and Scores):\n")
            if "round_1_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["round_1_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A'):.1f}, Comp: {score.get('computation_score', 'N/A'):.1f})**:\n")
                    f.write(f"  - Verification: {score.get('verification_step', 'N/A')}\n")
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
            
            f.write("\n#### Round 2 (Final Solutions and Scores):\n")
            if "final_round_results" in critic_data.get("full_data", {}):
                for j, item in enumerate(critic_data["full_data"]["final_round_results"]):
                    score = item.get("score", {})
                    f.write(f"**Agent {j+1} (Logic: {score.get('logic_score', 'N/A'):.1f}, Comp: {score.get('computation_score', 'N/A'):.1f})**:\n")
                    f.write(f"  - Verification: {score.get('verification_step', 'N/A')}\n")
                    f.write(f"  - Critique: {score.get('critique', 'N/A')}\n")
                    f.write(f"  - Solution:\n```\n{item.get('solution', 'N/A')}\n```\n")
            f.write("\n---\n")

    print(f"Success! Detailed report saved to: {report_file}")

if __name__ == "__main__":
    main()