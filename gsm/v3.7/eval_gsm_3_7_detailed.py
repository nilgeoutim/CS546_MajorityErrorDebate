import json
import re
import numpy as np
import os

def solve_math_problems(input_str):
    pattern = r"\d+\.?\d*"
    matches = re.findall(pattern, input_str)
    if matches:
        return matches[-1]
    return None

def parse_answer(input_str):
    pattern = r"\\boxed\{([0-9.,$]*)\}"
    matches = re.findall(pattern, input_str)
    if not matches:
        pattern = r"\{([0-9.,$]*)\}"
        matches = re.findall(pattern, input_str)

    solution = None
    for match_str in matches[::-1]:
        solution = re.sub(r"[^0-9.]", "", match_str)
        if solution:
            break
    
    if solution is None:
        solution = solve_math_problems(input_str)
        
    return solution

def check_correctness(gt, pred_solution):
    gt_answer = solve_math_problems(str(gt))
    pred_answer = parse_answer(str(pred_solution))

    if gt_answer is None or pred_answer is None:
        return 0

    try:
        if float(gt_answer) == float(pred_answer):
            return 1
        else:
            return 0
    except:
        return 0

if __name__ == "__main__":
    file_name = "gsm/v3.7/gsm_critic_actor_3_7.json"
    print(f"Loading {file_name}...")
    
    if not os.path.exists(file_name):
         # Try relative path if run from gsm/v3.7
         file_name = "gsm_critic_actor_3_7.json"
         
    try:
        response_dict = json.load(open(file_name, "r", encoding='utf-8'))
    except FileNotFoundError:
        print(f"Error: File {file_name} not found.")
        exit()

    questions = list(response_dict.keys())
    total_questions = len(questions)
    print(f"Total Questions: {total_questions}")

    # Metrics
    # R1: A0, A1, A2
    # R3: A0, A1, A2
    # Voting (Temp Decision)
    # Final (R4 Decision)
    
    stats = {
        "R1_A0": 0, "R1_A1": 0, "R1_A2": 0,
        "R3_A0": 0, "R3_A1": 0, "R3_A2": 0,
        "Voting": 0,
        "Final": 0
    }
    
    # Track Fallback & Recanting
    fallback_count = 0
    recanted_count = 0
    recanted_correct = 0 # How often did recanting lead to correct answer?

    for question in questions:
        data = response_dict[question]
        gt = data["ground_truth"]
        if "####" in str(gt):
            gt = str(gt).split("####")[-1].strip()
            
        # Round 1
        r1_list = data.get("round_1", [])
        for agent in r1_list:
            idx = agent.get("id")
            sol = agent.get("solution")
            if idx == 0: stats["R1_A0"] += check_correctness(gt, sol)
            elif idx == 1: stats["R1_A1"] += check_correctness(gt, sol)
            elif idx == 2: stats["R1_A2"] += check_correctness(gt, sol)

        # Round 3
        r3_list = data.get("round_3_finals", [])
        for agent in r3_list:
            idx = agent.get("original_idx")
            sol = agent.get("answer") # This is already extracted answer
            if idx == 0: stats["R3_A0"] += check_correctness(gt, sol)
            elif idx == 1: stats["R3_A1"] += check_correctness(gt, sol)
            elif idx == 2: stats["R3_A2"] += check_correctness(gt, sol)
            
        # Voting (Temp Decision)
        temp_dec = data.get("temp_decision")
        stats["Voting"] += check_correctness(gt, temp_dec)
        
        # Final Decision
        final_dec = data.get("final_decision")
        is_final_correct = check_correctness(gt, final_dec)
        stats["Final"] += is_final_correct
        
        # Metadata
        if data.get("fallback_triggered"):
            fallback_count += 1
            
        if data.get("recanted"):
            recanted_count += 1
            if is_final_correct:
                recanted_correct += 1

    # Print Report
    print("\n" + "="*50)
    print("DETAILED ACCURACY REPORT (Version 3.7)")
    print("="*50)
    
    print(f"{'Stage / Agent':<25} | {'Accuracy':<10}")
    print("-" * 40)
    
    # Round 1
    print(f"{'R1: Executor (A0)':<25} | {stats['R1_A0']/total_questions*100:<6.2f}%")
    print(f"{'R1: Critic (A1)':<25} | {stats['R1_A1']/total_questions*100:<6.2f}%")
    print(f"{'R1: Synthesizer (A2)':<25} | {stats['R1_A2']/total_questions*100:<6.2f}%")
    print("-" * 40)
    
    # Round 3
    print(f"{'R3: Executor (A0)':<25} | {stats['R3_A0']/total_questions*100:<6.2f}%")
    print(f"{'R3: Critic (A1)':<25} | {stats['R3_A1']/total_questions*100:<6.2f}%")
    print(f"{'R3: Synthesizer (A2)':<25} | {stats['R3_A2']/total_questions*100:<6.2f}%")
    print("-" * 40)
    
    # System
    print(f"{'Voting (Pre-Verify)':<25} | {stats['Voting']/total_questions*100:<6.2f}%")
    print(f"{'FINAL SYSTEM':<25} | {stats['Final']/total_questions*100:<6.2f}%")
    
    print("="*50)
    print("MECHANISM STATS")
    print("-" * 40)
    print(f"Fallback Triggered: {fallback_count}/{total_questions} ({fallback_count/total_questions*100:.1f}%)")
    print(f"Recanted (R4):      {recanted_count}/{total_questions} ({recanted_count/total_questions*100:.1f}%)")
    if recanted_count > 0:
        print(f"Recanted Accuracy:  {recanted_correct}/{recanted_count} ({recanted_correct/recanted_count*100:.1f}%)")
    print("="*50)
