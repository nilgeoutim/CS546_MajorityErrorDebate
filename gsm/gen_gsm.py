# import openai
import transformers
import torch
import json
import numpy as np
import random
from tqdm import tqdm
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

def construct_message(agents, question, idx):
    if len(agents) == 0:
        return {"role": "user", "content": "Can you double check that your answer is correct. Please reiterate your answer, with your final answer a single numerical number, in the form \\boxed{{answer}}."}

    prefix_string = "These are the solutions to the problem from other agents: "

    for agent in agents:
        agent_response = agent[idx]["content"]
        response = "\n\n One agent solution: ```{}```".format(agent_response)

        prefix_string = prefix_string + response

    prefix_string = prefix_string + """\n\n Using the solutions from other agents as additional information, can you provide your answer to the math problem? \n The original math problem is {}. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step.""".format(question)
    return {"role": "user", "content": prefix_string}


def construct_assistant_message(completion):
    # content = completion["choices"][0]["message"]["content"]
    # content = completion[0]["generated_text"][-1] # transformers
    content = completion.outputs[0].text
    return {"role": "assistant", "content": content}


def read_jsonl(path: str):
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]


if __name__ == "__main__":
    agents = 3
    rounds = 3
    random.seed(0)

    model_id = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    # # transformers
    # pipeline = transformers.pipeline(
    #     "text-generation",
    #     model=model_id,
    #     model_kwargs={"dtype": torch.bfloat16}, # torch_dtype is deprecated
    #     device_map="auto",
    # )
    # pipeline.tokenizer.pad_token_id = pipeline.tokenizer.eos_token_id

    # vllm Python API
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    llm = LLM(
        model=model_id,
        dtype="bfloat16",
        gpu_memory_utilization=0.9,
    )
    sampling_params = SamplingParams(
        max_tokens=512,
    )

    generated_description = {}

    questions = read_jsonl("gsm_test.jsonl")
    random.shuffle(questions)

    for data in tqdm(questions[:100], desc="Processing questions"):
        question = data['question']
        answer = data['answer']

        agent_contexts = [[{"role": "system", "content": "You are a helpful assistant."},
                           {"role": "user", "content": """Can you solve the following math problem? {} Explain your reasoning. Your final answer should be a single numerical number, in the form \\boxed{{answer}}, at the end of your response. Let's think step by step.""".format(question)}]
                           for agent in range(agents)]

        for round in range(rounds):
            prompts = []
            for i, agent_context in enumerate(agent_contexts):
                if round != 0:
                    agent_contexts_other = agent_contexts[:i] + agent_contexts[i+1:]
                    message = construct_message(agent_contexts_other, question, 2*round) # no -1 because there's an additional system prompt
                    agent_context.append(message)
                # vllm
                prompt = tokenizer.apply_chat_template(
                    agent_context, 
                    tokenize=False, 
                    add_generation_prompt=True
                )
                prompts.append(prompt)

            # # transformer
            # completions = pipeline(
            #     prompts,
            #     max_new_tokens=256,
            #     pad_token_id=pipeline.tokenizer.eos_token_id,
            #     batch_size=agents,
            # )

            # vllm Python API
            outputs = llm.generate(prompts, sampling_params, use_tqdm=False)

            for i, out in enumerate(outputs):
                assistant_message = construct_assistant_message(out)
                agent_contexts[i].append(assistant_message)

        generated_description[question] = (agent_contexts, answer)

    json.dump(generated_description, open("results/gsm_{}_{}.json".format(agents, rounds), "w"))

    # import pdb
    # pdb.set_trace()
    # print(answer)
    # print(agent_context)
