import json
import re
import numpy as np

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
    gt_answer = solve_math_problems(gt)
    pred_answer = parse_answer(pred_solution)

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
    file_name = "gsm/gsm_critic_actor_3_7.json"
    print(f"Loading {file_name}...")
    try:
        response_dict = json.load(open(file_name, "r"))
    except FileNotFoundError:
        print(f"Error: File {file_name} not found.")
        exit()

    questions = list(response_dict.keys())
    total_questions = len(questions)
    print(f"Total Questions: {total_questions}")

    # Data structures: [Round][Agent] -> {sum_logic, sum_comp, sum_total, correct_count}
    # Rounds: 0-3 (R1-R4), Agents: 0-2 (A1-A3)
    stats = [[{'logic': 0.0, 'comp': 0.0, 'total': 0.0, 'correct': 0} for _ in range(3)] for _ in range(4)]

    for question in questions:
        data = response_dict[question]
        gt = data["ground_truth"]
        all_rounds = data.get("all_rounds_data", [])

        # Ensure we have 4 rounds
        if len(all_rounds) < 4:
            # Fallback or skip if incomplete data (though structure seemed consistent)
            continue

        for r in range(4):
            round_data = all_rounds[r]
            for a in range(3):
                agent_data = round_data[a]
                
                # Scores
                score_data = agent_data.get("score", {})
                logic = score_data.get("logic_score", 0.0)
                comp = score_data.get("computation_score", 0.0)
                
                # Handle cases where score might be None or missing
                if logic is None: logic = 0.0
                if comp is None: comp = 0.0
                
                total = logic + comp # Assuming Total is sum

                stats[r][a]['logic'] += logic
                stats[r][a]['comp'] += comp
                stats[r][a]['total'] += total

                # Accuracy
                solution = agent_data.get("solution", "")
                is_correct = check_correctness(gt, solution)
                stats[r][a]['correct'] += is_correct

    # Print Tables
    print("\n" + "="*60)
    print("TABLE 1: Average Scores (Logic, Compute, Total)")
    print("="*60)
    print(f"{'Agent/Round':<15} | {'Logic':<10} | {'Compute':<10} | {'Total':<10}")
    print("-" * 55)

    for r in range(4):
        for a in range(3):
            label = f"A{a+1}R{r+1}"
            avg_logic = stats[r][a]['logic'] / total_questions
            avg_comp = stats[r][a]['comp'] / total_questions
            avg_total = stats[r][a]['total'] / total_questions
            print(f"{label:<15} | {avg_logic:<10.2f} | {avg_comp:<10.2f} | {avg_total:<10.2f}")

    print("\n" + "="*40)
    print("TABLE 2: Average Accuracy")
    print("="*40)
    print(f"{'Agent/Round':<15} | {'Accuracy':<10}")
    print("-" * 30)

    for r in range(4):
        for a in range(3):
            label = f"A{a+1}R{r+1}"
            accuracy = (stats[r][a]['correct'] / total_questions) * 100
            print(f"{label:<15} | {accuracy:<10.2f}%")
