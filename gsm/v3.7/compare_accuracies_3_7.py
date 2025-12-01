import json
import re
import os
import numpy as np

def normalize_number(num_str):
    """
    Normalizes a number string for comparison.
    Removes commas, handles floating point differences.
    Returns float if possible, else original string.
    """
    if not num_str:
        return None
    
    # Remove commas
    clean_str = str(num_str).replace(',', '').strip()
    
    try:
        return float(clean_str)
    except ValueError:
        return clean_str

def is_correct(prediction, ground_truth):
    """
    Checks if prediction matches ground truth.
    """
    pred_norm = normalize_number(prediction)
    gt_norm = normalize_number(ground_truth)
    
    if pred_norm is None or gt_norm is None:
        return False
        
    if isinstance(pred_norm, float) and isinstance(gt_norm, float):
        return np.isclose(pred_norm, gt_norm, atol=1e-5)
    
    return str(pred_norm) == str(gt_norm)

def analyze_results(file_path):
    print(f"Analyzing: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total = 0
    correct = 0
    fallback_count = 0
    fallback_correct = 0
    
    # For detailed error analysis
    errors = []

    for question, result in data.items():
        total += 1
        
        ground_truth = result.get('ground_truth')
        # Extract number from ground truth if it contains "####"
        if "####" in str(ground_truth):
            ground_truth = str(ground_truth).split("####")[-1].strip()
            
        final_decision = result.get('final_decision')
        fallback_triggered = result.get('fallback_triggered', False)
        
        if fallback_triggered:
            fallback_count += 1
            
        if is_correct(final_decision, ground_truth):
            correct += 1
            if fallback_triggered:
                fallback_correct += 1
        else:
            errors.append({
                "question": question,
                "ground_truth": ground_truth,
                "prediction": final_decision,
                "fallback": fallback_triggered
            })

    accuracy = (correct / total) * 100 if total > 0 else 0
    fallback_rate = (fallback_count / total) * 100 if total > 0 else 0
    fallback_accuracy = (fallback_correct / fallback_count) * 100 if fallback_count > 0 else 0

    print("="*50)
    print(f"RESULTS REPORT: {os.path.basename(file_path)}")
    print("="*50)
    print(f"Total Questions: {total}")
    print(f"Correct:         {correct}")
    print(f"Accuracy:        {accuracy:.2f}%")
    print("-" * 30)
    print(f"Fallback Triggered: {fallback_count} ({fallback_rate:.2f}%)")
    print(f"Fallback Accuracy:  {fallback_accuracy:.2f}%")
    print("="*50)
    
    if errors:
        print("\nSample Errors:")
        for i, err in enumerate(errors[:5]):
            print(f"{i+1}. GT: {err['ground_truth']} | Pred: {err['prediction']} | Fallback: {err['fallback']}")
            print(f"   Q: {err['question'][:100]}...")

if __name__ == "__main__":
    target_file = 'gsm/gsm_critic_actor_3_7.json'
    analyze_results(target_file)
