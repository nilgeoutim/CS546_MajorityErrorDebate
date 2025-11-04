import json
import numpy as np
import re
from tqdm import tqdm

# --- Helper Functions from original eval_gsm.py ---
# These are copied directly from your eval_gsm.py [cite: `gsm/eval_gsm.py`]

def solve_math_problems(input_str):
    pattern = r"\d+\.?\d*"
    matches = re.findall(pattern, input_str)
    if matches:
        return matches[-1]
    return None

def parse_answer(input_str):
    # Updated pattern to find \boxed{...}
    pattern = r"\\boxed\{([0-9.,$]*)\}"
    matches = re.findall(pattern, input_str)

    solution = None
    for match_str in matches[::-1]:
        solution = re.sub(r"[^0-9.]", "", match_str)
        if solution:
            break
    
    # Fallback if \boxed{} is not found
    if solution is None:
        # Look for numbers near the end
        pattern = r"(\d+\.?\d*)\s*$"
        matches = re.findall(pattern, input_str)
        if matches:
            solution = matches[-1]

    return solution

def most_frequent(List):
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

def compute_accuracy(gt, pred_solutions):
    # Extract ground truth answer
    gt_pattern = r"#### (\d+\.?\d*)"
    gt_match = re.search(gt_pattern, gt)
    if not gt_match:
        print(f"Warning: Could not parse ground truth: {gt}")
        return None
    gt_answer = gt_match.group(1)

    pred_answers = []
    for pred_solution in pred_solutions:
        pred_answer = parse_answer(pred_solution)
        
        # If parse_answer fails, try the broader solve_math_problems
        if pred_answer is None:
            pred_answer = solve_math_problems(pred_solution)
        
        if pred_answer is not None:
            pred_answers.append(pred_answer)

    if not pred_answers:
        return 0  # All agents failed to provide a parsable answer

    # Get the majority vote
    final_pred_answer = most_frequent(pred_answers)

    if final_pred_answer is None:
        return 0

    try:
        if float(gt_answer) == float(final_pred_answer):
            return 1
        else:
            return 0
    except ValueError:
        print(f"Warning: ValueError comparing GT '{gt_answer}' with PRED '{final_pred_answer}'")
        return 0
    except:
        return 0

# --- Main Evaluation ---

if __name__ == "__main__":
    # Update this filename to match the output of your gen script
    results_filename = "gsm_critic_actor_3_2.json" 
    
    try:
        response_dict = json.load(open(results_filename, "r"))
    except FileNotFoundError:
        print(f"Error: Results file not found: {results_filename}")
        print("Please run gen_math_critic_actor.py first.")
        exit()

    questions = list(response_dict.keys())
    accuracies = []

    print(f"Evaluating results from {results_filename}...")

    for question in tqdm(questions, desc="Evaluating Questions"):
        data = response_dict[question]
        gt = data["ground_truth"]
        final_round_data = data["final_round_results"]
        
        # Get the final solution text from all agents
        pred_solutions = [item["solution"] for item in final_round_data]

        accurate = compute_accuracy(gt, pred_solutions)

        if accurate is not None:
            accuracies.append(float(accurate))
        else:
            print(f"Warning: Skipping question due to GT parsing error: {question}")

    if accuracies:
        mean_accuracy = np.mean(accuracies)
        std_err = np.std(accuracies) / (len(accuracies) ** 0.5)
        print("\n--- Final Results ---")
        print(f"Total questions evaluated: {len(accuracies)}")
        print(f"Accuracy: {mean_accuracy * 100:.2f}%")
        print(f"Standard Error: {std_err:.4f}")
    else:
        print("No questions were evaluated.")
