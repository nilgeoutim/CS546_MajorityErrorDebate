import json
import re
import os

def robust_extract_answer(text):
    # 1. Try to find "Code Execution Output:" and search after it
    if "Code Execution Output:" in text:
        parts = text.split("Code Execution Output:")
        output_part = parts[-1]
        
        # Look for boxed in the output part
        match = re.search(r'\\boxed\{([^\}]+)\}', output_part)
        if match:
            return match.group(1)
            
        # Fallback: look for last number in output part
        numbers = re.findall(r'-?\d+\.?\d*', output_part)
        if numbers:
            return numbers[-1]

    # 2. If not found or no execution output, try to find the LAST boxed in the whole text
    # (The code usually comes first, output last)
    matches = re.findall(r'\\boxed\{([^\}]+)\}', text)
    if matches:
        # Check if the last match looks like code (contains quotes or +)
        last_match = matches[-1]
        if '"' not in last_match and '+' not in last_match:
            return last_match
        
        # If last match is code, try second to last?
        if len(matches) > 1:
            second_last = matches[-2]
            if '"' not in second_last and '+' not in second_last:
                return second_last

    # 3. Fallback to original logic but filter bad chars
    match = re.search(r'\\boxed\{([^\}]+)\}', text)
    if match:
        candidate = match.group(1)
        if '"' not in candidate and '+' not in candidate:
            return candidate
            
    return "Error"

file_path = 'gsm/v3.7/gsm_critic_actor_3_7.json'
print(f"Repairing {file_path}...")

with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

fixed_count = 0
for q, res in data.items():
    r4_text = res.get('round_4_verification', "")
    current_final = res.get('final_decision', "")
    
    # Check if current decision looks broken (contains quotes or + or is empty)
    if '"' in current_final or '+' in current_final or not current_final or current_final == "Error":
        # Attempt repair
        if r4_text:
            new_ans = robust_extract_answer(r4_text)
            if new_ans != "Error" and new_ans != current_final:
                res['final_decision'] = new_ans
                fixed_count += 1
                # Also update recanted status if needed? 
                # (If it was "Error" before, it might have been counted as recanted=True but final=Error)
                
                # If the new answer is different from temp_decision, ensure recanted is True
                temp = res.get('temp_decision')
                if temp != new_ans:
                    res['recanted'] = True
                else:
                    res['recanted'] = False # Actually verified?

print(f"Fixed {fixed_count} entries.")

with open(file_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print("Done.")
