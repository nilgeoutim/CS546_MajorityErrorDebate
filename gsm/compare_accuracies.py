import json
import numpy as np
import re
from tqdm import tqdm

# =====================================================================================
# SECTION 1: Core Evaluation Functions (from eval_math_critic_actor.py)
# These are the best evaluation logic we will apply uniformly.
# =====================================================================================

def parse_answer(input_str: str) -> str:
    """
    Extracts the answer from \boxed{...}.
    This is the main parser from eval_math_critic_actor.py [cite: `eval_math_critic_actor.py`].
    """
    pattern = r"\\boxed\{([0-9.,$]*)\}"
    matches = re.findall(pattern, input_str)

    solution = None
    for match_str in matches[::-1]:
        # Remove non-numeric/non-dot characters (including '$' and ',')
        solution = re.sub(r"[^0-9.]", "", match_str)
        if solution:
            break
    
    # Fallback Logic: If \boxed{} is not found, find the number at the end of the string
    if solution is None:
        pattern = r"(\d+\.?\d*)\s*$"
        matches = re.findall(pattern, input_str)
        if matches:
            solution = matches[-1]

    return solution

def solve_math_problems(input_str: str) -> str:
    """
    Fallback function used to find the last number in the string.
    From eval_gsm.py [cite: `eval_gsm.py`].
    """
    pattern = r"\d+\.?\d*"
    matches = re.findall(pattern, input_str)
    if matches:
        return matches[-1]
    return None

def most_frequent(List: list) -> str:
    """
    Finds the majority vote from the list.
    From eval_math_critic_actor.py [cite: `eval_math_critic_actor.py`].
    """
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

def compute_accuracy(gt: str, pred_solutions: list) -> int:
    """
    Unified Scorer: Compares the majority vote against the ground truth.
    Uses the most robust GT parser from eval_math_critic_actor.py [cite: `eval_math_critic_actor.py`].
    """
    # 1. Extract Ground Truth (GT)
    gt_pattern = r"#### (\d+\.?\d*)"
    gt_match = re.search(gt_pattern, gt)
    if not gt_match:
        # print(f"Warning: Could not parse ground truth: {gt}")
        return None  # Cannot parse GT, skipping this problem
    gt_answer = gt_match.group(1)

    # 2. Extract Predicted Answers
    pred_answers = []
    for pred_solution in pred_solutions:
        pred_answer = parse_answer(pred_solution) # First try \boxed{}
        
        if pred_answer is None:
            pred_answer = solve_math_problems(pred_solution) # Then try the last number
        
        if pred_answer is not None:
            pred_answers.append(pred_answer)

    if not pred_answers:
        return 0  # All agents failed to provide a parseable answer

    # 3. Find the Majority Vote
    final_pred_answer = most_frequent(pred_answers)
    if final_pred_answer is None:
        return 0

    # 4. Comparison
    try:
        # We compare floats for numerical problems
        if float(gt_answer) == float(final_pred_answer):
            return 1
        else:
            return 0
    except ValueError:
        # print(f"Warning: ValueError comparing GT '{gt_answer}' with PRED '{final_pred_answer}'")
        return 0
    except:
        return 0

# =====================================================================================
# SECTION 2: Evaluators for Different JSON Formats
# =====================================================================================

def evaluate_critic_actor_file(filename="gsm_critic_actor_3_2.json"):
    """
    Evaluates the new "Critic-Actor" file format [cite: `gsm_critic_actor_3_2.json`].
    """
    print(f"Evaluating {filename}...")
    try:
        response_dict = json.load(open(filename, "r"))
    except FileNotFoundError:
        print(f"Error: File not found {filename}")
        return 0.0

    questions = list(response_dict.keys())
    accuracies = []

    for question in tqdm(questions, desc=f"Evaluating {filename}"):
        data = response_dict[question]
        gt = data["ground_truth"]
        
        # Extract all solutions from the "final round"
        final_round_data = data["final_round_results"]
        pred_solutions = [item["solution"] for item in final_round_data]
        
        accurate = compute_accuracy(gt, pred_solutions)

        if accurate is not None:
            accuracies.append(float(accurate))

    return np.mean(accuracies) if accuracies else 0.0

def evaluate_original_file(filename="gsm_3_3.json"):
    """
    Evaluates the original "Free Debate" file format [cite: `gsm_3_3.json`].
    """
    print(f"\nEvaluating {filename}...")
    try:
        response_dict = json.load(open(filename, "r"))
    except FileNotFoundError:
        print(f"Error: File not found {filename}")
        return 0.0

    questions = list(response_dict.keys())
    accuracies = []

    for question in tqdm(questions, desc=f"Evaluating {filename}"):
        # The original file [cite: `gsm_3_3.json`] has a different data structure
        responses, gt = response_dict[question]
        
        # Extract each agent's response from the last round
        # This aligns with the logic of eval_gsm.py [cite: `eval_gsm.py`]
        pred_solutions = []
        for response_context_list in responses:
            pred_solutions.append(response_context_list[-1]['content'])
        
        accurate = compute_accuracy(gt, pred_solutions)

        if accurate is not None:
            accuracies.append(float(accurate))

    return np.mean(accuracies) if accuracies else 0.0

# =====================================================================================
# SECTION 3: Main Execution
# =====================================================================================

if __name__ == "__main__":
    # Define filenames
    critic_actor_file = 'gsm_critic_actor_3_2.json'
    original_file = 'gsm_3_3.json'

    # Run both evaluations
    acc_critic = evaluate_critic_actor_file(critic_actor_file)
    acc_original = evaluate_original_file(original_file)

    # Print Final Comparison Report
    print("\n" + "="*30)
    print("--- Experiment Results Comparison ---")
    print(f"Original Debate ({original_file}): {acc_original * 100:.1f}%")
    print(f"Critic-Actor ({critic_actor_file}): {acc_critic * 100:.1f}%")
    print("="*30)
    print(f"Performance Improvement: {(acc_critic - acc_original) * 100:.1f} percentage points")