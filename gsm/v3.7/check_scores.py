import json
import numpy as np

file_path = 'gsm/v3.7/gsm_critic_actor_3_7.json'
with open(file_path, 'r') as f:
    data = json.load(f)

total = len(data)
empty_scores = {0: 0, 1: 0, 2: 0}
total_scores = {0: 0, 1: 0, 2: 0}

for q, res in data.items():
    scores = res.get('round_2_scores', {})
    for i in range(3):
        s_list = scores.get(str(i), [])
        if not s_list:
            empty_scores[i] += 1
        else:
            total_scores[i] += len(s_list)

print(f"Total Questions: {total}")
print("Empty Score Lists per Agent (Indices 0, 1, 2):")
print(empty_scores)
print("Total Scores Recorded per Agent:")
print(total_scores)
