import json
import random
import os
from openai import OpenAI


CLIENT = OpenAI(
    api_key="" # your OpenAI API Key
)

AGENT_MODEL = "gpt-3.5-turbo"
CRITIC_MODEL = "gpt-5.1"
AGENTS_COUNT = 3
ROUNDS = 4
SAMPLE_SIZE = 100 

def get_critic_feedback(question, agent_responses):
    """
    Let critic give feedbacks to the anwser of agents
    """
    responses_text = ""
    for i, response in enumerate(agent_responses):
        responses_text += f"Agent {i+1} Solution:\n```\n{response}\n```\n\n"

    prompt = f"""
    I am organizing a math debate. The original problem is:
    "{question}"

    Here are the solutions provided by {len(agent_responses)} different agents:
    {responses_text}

    As a senior mathematician and judge, please evaluate these solutions.
    1. Identify which agents (if any) are correct.
    2. Point out specific logical errors or calculation mistakes in the incorrect solutions.
    3. Provide a consolidated hint or guidance to help them converge to the correct answer in the next round.
    
    Your response should be constructive and guide them towards the truth without just giving the final number immediately if possible, encourage them to think.
    """

    try:
        completion = CLIENT.responses.create(
            model=CRITIC_MODEL,
            input=[
                {"role": "system", "content": "You are a strict but helpful math critic."},
                {"role": "user", "content": prompt}
            ]
        )
        return completion.output_text
    except Exception as e:
        print(f"Critic Error: {e}")
        return "Critic is currently unavailable. Please double check your own steps."

def construct_message(agents_contexts, current_agent_index, question, round_idx, critic_feedback):
    """
    Construct User Message for the next round
    Include anwsers from other agents and the feedback of the critic
    """
    
    prefix_string = "Here are the solutions from other agents in the previous round:\n"

    other_agents_indices = [i for i in range(len(agents_contexts)) if i != current_agent_index]
    
    for idx in other_agents_indices:
        last_response = agents_contexts[idx][-1]["content"]
        prefix_string += f"\n\nAgent {idx+1} solution: ```{last_response}```"

    prefix_string += f"\n\n----------------\n"
    prefix_string += f"Here is the feedback from the Judge (Critic) regarding all solutions:\n{critic_feedback}\n"
    prefix_string += f"----------------\n\n"

    prefix_string += f"""Using the solutions from other agents and the Judge's feedback, please review your previous answer.
    The original math problem is: {question}
    
    Please provide your updated solution. 
    You must strictly follow this format: Explain your reasoning step by step, and put your final numerical answer within \\boxed{{}}. 
    Example: \\boxed{{42}}."""
    
    return {"role": "user", "content": prefix_string}

def read_jsonl(path: str):
    data = []
    if not os.path.exists(path):
        print(f"Warning: File {path} not found. Using dummy data for testing.")
        return [{"question": "Janet has 3 apples. She buys 2 more. How many does she have?", "answer": "5"}]
    
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                data.append(json.loads(line))
    return data

if __name__ == "__main__":
    random.seed(0)
    
    generated_description = {}
    questions = read_jsonl("gsm_majority_error.jsonl")
    
    target_questions = questions[:SAMPLE_SIZE] if len(questions) >= SAMPLE_SIZE else questions

    print(f"Starting debate on {len(target_questions)} questions with Critic: {CRITIC_MODEL}...")

    for q_idx, data in enumerate(target_questions):
        question = data['question']
        answer = data['answer']
        
        print(f"Processing Question {q_idx + 1}: {question[:50]}...")
        agent_contexts = []
        for agent_id in range(AGENTS_COUNT):
            agent_contexts.append([
                {"role": "system", "content": "You are a helpful assistant. Always format your final answer as \\boxed{number}."},
                {"role": "user", "content": f"Can you solve the following math problem? {question} Explain your reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step."}
            ])

        # debate for multiple rounds
        for round_num in range(ROUNDS):
            print(f"  - Round {round_num + 1}...")
            
            current_round_responses = []
            
            for i in range(AGENTS_COUNT):
                full_history = agent_contexts[i]
                pruned_messages = []
                pruned_messages.append(full_history[0])
                pruned_messages.append(full_history[1])
                if round_num > 0:
                    pruned_messages.append(full_history[-2])
                    pruned_messages.append(full_history[-1])
                
                try:
                    completion = CLIENT.responses.create(
                        model=AGENT_MODEL,
                        input=pruned_messages
                    )
                    content = completion.output_text
                except Exception as e:
                    print(f"    Error calling Agent {i}: {e}")
                    content = "Error generating response."

                agent_contexts[i].append({"role": "assistant", "content": content})
                current_round_responses.append(content)

            if round_num < ROUNDS - 1:
                print("    > Critic is evaluating...")
                critic_feedback = get_critic_feedback(question, current_round_responses)
                
                for i in range(AGENTS_COUNT):
                    next_message = construct_message(
                        agents_contexts=agent_contexts,
                        current_agent_index=i,
                        question=question,
                        round_idx=round_num,
                        critic_feedback=critic_feedback
                    )
                    agent_contexts[i].append(next_message)

        # generated_description[question] = {
        #     "agent_contexts": agent_contexts,
        #     "ground_truth": answer
        # }
        generated_description[question] = (agent_contexts, answer)

    output_filename = f"gsm_{AGENTS_COUNT}_{ROUNDS}_{AGENT_MODEL}_with_{CRITIC_MODEL}_critic.json"
    with open(output_filename, "w", encoding='utf-8') as f:
        json.dump(generated_description, f, indent=2, ensure_ascii=False)

    print(f"Finished. Results saved to {output_filename}")
    
    # import pdb; pdb.set_trace()