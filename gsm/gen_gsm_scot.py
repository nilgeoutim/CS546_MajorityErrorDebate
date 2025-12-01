import openai
import json
import numpy as np
import random
import os
from tqdm import tqdm

def construct_assistant_message(completion):
    content = completion.choices[0].message.content
    return {"role": "assistant", "content": content}

def read_jsonl(path: str):
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]

if __name__ == "__main__":

    random.seed(0)
    np.random.seed(0)

    os.makedirs("results", exist_ok=True)

    output_file = "results/gsm_scot_baseline.json"

    # load or init
    if os.path.exists(output_file):
        with open(output_file, "r") as f:
            generated_description = json.load(f)
            print(f"Loaded {len(generated_description)} existing results")
    else:
        generated_description = {}
        with open(output_file, "w") as f:
            json.dump({}, f, indent=2)
        print("Created new output file")

    questions = read_jsonl("gsm_majority_error.jsonl")

    client = openai.OpenAI()

    # SCoT prompt (single-query)
    SCOT_PROMPT = """
You are solving a math reasoning problem.

### Step 1 — Strategy Elicitation
Identify the most effective, reliable, and generalizable strategy to solve this problem.
**Do NOT compute the answer in this step. Only describe the method.**

### Step 2 — Strategy-Guided Reasoning
Now apply ONLY the strategy you selected.
Solve step by step clearly.

### Final Answer
Return the final numerical answer in the form: \\boxed{{answer}}

Problem:
{}
"""

    for data in tqdm(questions):
        question = data["question"]
        answer = data["answer"]

        # skip if already done
        if question in generated_description:
            continue

        messages = [
            {
                "role": "user",
                "content": SCOT_PROMPT.format(question)
            }
        ]

        try:
            completion = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                n=1,
                temperature=0,  # deterministic for research
                top_p=1
            )

            assistant_message = construct_assistant_message(completion)
            messages.append(assistant_message)

            generated_description[question] = (messages, answer)

            # save progress
            with open(output_file, "w") as f:
                json.dump(generated_description, f, indent=2)

        except Exception as e:
            print("\nError:", e)
            print(f"Progress saved. {len(generated_description)} questions completed.")
            with open(output_file, "w") as f:
                json.dump(generated_description, f, indent=2)
            raise

    print(f"\nCompleted! Total saved: {len(generated_description)} questions → {output_file}")
