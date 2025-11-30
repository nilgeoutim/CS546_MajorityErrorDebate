import json
import numpy as np
import re

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

def is_correct(gt, pred):
    if pred is None:
        return False
    try:
        # Extract number from GT
        gt_pattern = r"#### (\d+\.?\d*)"
        gt_match = re.search(gt_pattern, gt)
        if not gt_match:
            return False
        gt_val = float(gt_match.group(1))
        pred_val = float(pred)
        return gt_val == pred_val
    except:
        return False

def analyze_results(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Metrics storage
    r1_scores_correct = {'logic': [], 'comp': []}
    r1_scores_incorrect = {'logic': [], 'comp': []}
    final_scores_correct = {'logic': [], 'comp': []}
    final_scores_incorrect = {'logic': [], 'comp': []}
    
    changed_answers = 0
    total_agents = 0
    consensus_count = 0
    total_questions = len(data)

    for question, details in data.items():
        gt = details['ground_truth']
        
        # Analyze Round 1
        r1_answers = []
        for agent_res in details['round_1_results']:
            sol = agent_res['solution']
            score = agent_res['score']
            ans = parse_answer(sol)
            r1_answers.append(ans)
            
            correct = is_correct(gt, ans)
            
            if correct:
                r1_scores_correct['logic'].append(score['logic_score'])
                r1_scores_correct['comp'].append(score['computation_score'])
            else:
                r1_scores_incorrect['logic'].append(score['logic_score'])
                r1_scores_incorrect['comp'].append(score['computation_score'])

        # Analyze Final Round
        final_answers = []
        for i, agent_res in enumerate(details['final_round_results']):
            sol = agent_res['solution']
            score = agent_res['score']
            ans = parse_answer(sol)
            final_answers.append(ans)
            
            correct = is_correct(gt, ans)
            
            if correct:
                final_scores_correct['logic'].append(score['logic_score'])
                final_scores_correct['comp'].append(score['computation_score'])
            else:
                final_scores_incorrect['logic'].append(score['logic_score'])
                final_scores_incorrect['comp'].append(score['computation_score'])
            
            # Check if answer changed
            if r1_answers[i] != ans:
                changed_answers += 1
            total_agents += 1

        # Check Consensus
        if len(set(final_answers)) == 1:
            consensus_count += 1

    print("=== Analysis Results ===")
    print(f"Total Questions: {total_questions}")
    print(f"Consensus Rate: {consensus_count/total_questions*100:.2f}%")
    print(f"Agent Answer Change Rate: {changed_answers/total_agents*100:.2f}%")
    
    print("\n--- Round 1 Scores ---")
    print(f"R1 Correct Logic: {np.mean(r1_scores_correct['logic']):.2f}")
    print(f"R1 Correct Comp: {np.mean(r1_scores_correct['comp']):.2f}")
    print(f"R1 Incorrect Logic: {np.mean(r1_scores_incorrect['logic']):.2f}")
    print(f"R1 Incorrect Comp: {np.mean(r1_scores_incorrect['comp']):.2f}")
    
    print("\n--- Final Round Scores ---")
    print(f"Final Correct Logic: {np.mean(final_scores_correct['logic']):.2f}")
    print(f"Final Correct Comp: {np.mean(final_scores_correct['comp']):.2f}")
    print(f"Final Incorrect Logic: {np.mean(final_scores_incorrect['logic']):.2f}")
    print(f"Final Incorrect Comp: {np.mean(final_scores_incorrect['comp']):.2f}")

if __name__ == "__main__":
    analyze_results("gsm_critic_actor_3_2_v2_final_fix.json")
