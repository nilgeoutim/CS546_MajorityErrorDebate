import openai
import json
import numpy as np
import random
import os
from tqdm import tqdm

def construct_message(agents, question):
    # Final round: re-run SCoT verification
    if len(agents) == 0:
        return {
            "role": "user",
            "content": f"""
Other agents have produced their answers. Please double-check using Strategic Chain-of-Thought.

### Step 1 — Extract the best solving strategy
Identify the most effective and stable solving strategy. Do NOT compute here.

### Step 2 — Re-solve using this strategy
Follow the selected strategy step by step.

Final answer must be: \\boxed{{answer}}

Original problem:
{question}
"""
        }

    prefix = "Here are the reasoning attempts from other agents:\n\n"

    # Get last assistant message from each agent
    for agent in agents:
        last_assistant = next(
            (m["content"] for m in reversed(agent) if m["role"] == "assistant"),
            "(no answer)"
        )
        prefix += f"One agent solution:\n```{last_assistant}```\n\n"

    prefix += f"""
Using the above as hints, re-solve the problem using Strategic Chain-of-Thought:

### Step 1 — Identify the best strategy
Extract the most reliable and effective strategy (no computation here).

### Step 2 — Apply the strategy
Solve the problem strictly following the chosen strategy.

Return the final answer in \\boxed{{answer}}.

Original problem:
{question}
"""

    return {"role": "user", "content": prefix}


def construct_assistant_message(completion):
    content = completion.choices[0].message.content
    return {"role": "assistant", "content": content}


def read_jsonl(path: str):
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]

if __name__ == "__main__":
    agents = 5
    rounds = 4
    # random.seed(0)

    os.makedirs("results", exist_ok=True)
    
    output_file = "results/gsm_scot_{}_{}.json".format(agents, rounds)
    
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
    # random.shuffle(questions)

    client = openai.OpenAI()

    for data in tqdm(questions): # previously: [:100]
        question = data['question']
        answer = data['answer']
        
        # Skip if already processed
        if question in generated_description:
            continue

        SCoT_PROMPT = """

You are solving a math reasoning problem.

### Step 1 — Strategy Elicitation

Identify the most effective, reliable, and generalizable strategy to solve this problem.

Do NOT compute the answer in this step.

### Step 2 — Strategy-Guided Reasoning

Using ONLY the selected strategy, derive the answer step by step.

### Final Answer

Output the final numerical answer in the form: \\boxed{{answer}}

Problem:

{}

"""

        agent_contexts = [
            [{"role": "user", "content": SCoT_PROMPT.format(question)}]
            for agent in range(agents)
        ]

        try:
            for round in range(rounds):
                for i, agent_context in enumerate(agent_contexts):

                    if round != 0:
                        agent_contexts_other = agent_contexts[:i] + agent_contexts[i+1:]
                        message = construct_message(agent_contexts_other, question)

                        agent_context.append(message)

                    completion = client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            messages=agent_context,
                            n=1)
            
                    # completion = openai.ChatCompletion.create(
                    #           model="gpt-3.5-turbo",
                    #           messages=agent_context,
                    #           n=1)

                    assistant_message = construct_assistant_message(completion)
                    agent_context.append(assistant_message)

            # Save after each question is processed
            generated_description[question] = (agent_contexts, answer)
            
            with open(output_file, "w") as f:
                json.dump(generated_description, f, indent=2)
                
        except Exception as e:
            print(f"\nError processing question: {e}")
            print(f"Progress saved. {len(generated_description)} questions completed.")
            with open(output_file, "w") as f:
                json.dump(generated_description, f, indent=2)
            raise
    
    print(f"\nCompleted! Total: {len(generated_description)} questions saved to {output_file}")