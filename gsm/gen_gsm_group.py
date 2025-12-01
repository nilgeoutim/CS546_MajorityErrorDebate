import openai
import json
import numpy as np
import random
import os
import re
from tqdm import tqdm

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    print("Warning: tiktoken not available. Using approximate token counting.")

def construct_assistant_message(completion):
    content = completion.choices[0].message.content
    return {"role": "assistant", "content": content}


def read_jsonl(path: str):
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]


def extract_boxed_number(text: str):
    """
    extract answer from \boxed{123}; return None if extraction fails
    """
    m = re.search(r"\\boxed\{([^}]+)\}", text)
    if not m:
        return None
    return m.group(1).strip()


def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """
    count the number of tokens in the text
    """
    if TIKTOKEN_AVAILABLE:
        try:
            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except:
            # if the model name is not supported, use cl100k_base (the encoding of gpt-3.5-turbo and gpt-4)
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
    else:
        # approximate calculation: 1 token ≈ 4 characters
        return len(text) // 4


def truncate_to_tokens(text: str, max_tokens: int, model: str = "gpt-3.5-turbo") -> str:
    """
    truncate the text to the specified maximum number of tokens
    """
    if TIKTOKEN_AVAILABLE:
        try:
            encoding = tiktoken.encoding_for_model(model)
        except:
            encoding = tiktoken.get_encoding("cl100k_base")
        
        tokens = encoding.encode(text)
        if len(tokens) <= max_tokens:
            return text
        truncated_tokens = tokens[:max_tokens]
        return encoding.decode(truncated_tokens)
    else:
        # approximate truncation
        approx_chars = max_tokens * 4
        if len(text) <= approx_chars:
            return text
        return text[:approx_chars]


def run_group_debate(
    question: str,
    client,
    model: str = "gpt-3.5-turbo",
    M: int = 6,
    group_sizes = None,
    S: int = 2,   # number of stages
    R: int = 2,   # number of intra-group rounds in each stage
    temperature: float = 0.0,
    max_summary_tokens: int = 200,  # maximum number of tokens in the summary (constant C in the paper)
):
    """
    GroupDebate implementation (according to the paper):
    - M: total number of agents
    - group_sizes: if [2,2,2], will be split into 3 groups; if None, will be split into 2 groups by default
    - S: number of stages
    - R: number of intra-group rounds in each stage (R in the paper)
    - max_summary_tokens: maximum number of tokens in the summary (constant C in the paper, controlling token cost)
    
    Key features (according to the paper):
    1. Inter-group: only use the summary of the previous stage (forgetfulness)
    2. Summary token limit: all summaries are limited to max_summary_tokens
    3. Intra-group: use summary instead of full output (control token growth)
    """
    assert M > 0
    if group_sizes is None:
        # default: split into 2 groups
        half = M // 2
        group_sizes = [half, M - half]
    assert sum(group_sizes) == M, "the sum of group_sizes must be equal to M"

    # ===== 1. construct group划分 =====
    # groups: List[List[agent_id]]
    groups = []
    current = 0
    for size in group_sizes:
        group = list(range(current, current + size))
        groups.append(group)
        current += size

    # agent_messages[agent_id] = the message history of the current agent (here we can only store the current round)
    agent_messages = {i: [] for i in range(M)}
    # agent_last_output[agent_id] = the last output of the agent
    agent_last_output = {i: "" for i in range(M)}

    # stage_summaries[s][g] = the summary text of the g-th group in the s-th stage (for inter-group)
    stage_summaries = {}
    
    # group_summaries_per_round[s][r][g] = 第 s 个 stage、第 r 轮、第 g 个 group 的 summary（用于 intra-group）
    # implement forgetfulness: only keep the latest summary per round
    group_summaries_per_round = {}

    # ===== 2. pre-construct the system prompt for each agent (identify the identity) =====
    system_prompts = {}
    for i in range(M):
        system_prompts[i] = {
            "role": "system",
            "content": (
                f"You are Agent #{i} in a multi-agent math debate. "
                "You are good at step-by-step reasoning and must give your final numeric answer in the form "
                "\\boxed{answer} at the end."
            )
        }

    # ===== 3. start GroupDebate =====
    for s in range(1, S + 1):  # stage index: 1..S
        # whether this stage has a group summary from the previous stage
        has_prev_stage_summary = (s > 1 and (s - 1) in stage_summaries)

        # ---- Round 1 of this stage: inter-group + initial thinking ----
        # construct the input for each agent
        for g_idx, group in enumerate(groups):
            # the input context for the current group: the summary of all groups in the previous stage
            # according to the paper: "only the latest group summaries from previous stages"
            inter_group_text = ""
            if has_prev_stage_summary:
                prev_summaries = stage_summaries[s - 1]
                lines = []
                for other_g_idx, summ in prev_summaries.items():
                    lines.append(f"Group {other_g_idx} summary from previous stage:\n{summ}")
                inter_group_text = "\n\n".join(lines)

            for agent_id in group:
                # Round 1 is special: besides the question and the summary of the previous stage, there are no other agents in the group in the previous round (because the round1 of each stage is the starting point)
                user_content = (
                    "We are solving the following math problem:\n"
                    f"{question}\n\n"
                )

                if inter_group_text:
                    user_content += (
                        "Here are the summaries from all groups in the previous stage:\n"
                        f"{inter_group_text}\n\n"
                        "Please reconsider the problem carefully using this information. "
                        "Explain your reasoning step by step, then give your final answer in the form "
                        "\\boxed{answer} at the end."
                    )
                else:
                    # the first round of the first stage: only the question
                    user_content += (
                        "This is the first round of the debate. "
                        "Think step by step and propose your own solution. "
                        "Give your answer in the form \\boxed{answer} at the end."
                    )

                messages = [
                    system_prompts[agent_id],
                    {"role": "user", "content": user_content}
                ]

                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    n=1,
                    temperature=temperature,
                )
                assistant_message = construct_assistant_message(completion)
                agent_messages[agent_id] = messages + [assistant_message]
                agent_last_output[agent_id] = assistant_message["content"]

        # ---- Round 2..R: intra-group debate ----
        # according to the paper: Intra-group 使用 summary 而不是全量输出（控制 token 成本）
        # implement forgetfulness: only keep the latest summary per round, not keep the full history
        for r in range(2, R + 1):
            for g_idx, group in enumerate(groups):
                # generate the summary for the current group for this round (based on the outputs of all agents in the previous round)
                # 使用 summary 而不是全量输出（forgetfulness 模式，控制 token 成本）
                group_prev_outputs = []
                for agent_id in group:
                    group_prev_outputs.append(
                        f"Agent #{agent_id}'s answer:\n{agent_last_output[agent_id]}"
                    )
                group_prev_text = "\n\n".join(group_prev_outputs)
                
                # generate the group summary for this round (limit the token)
                summary_prompt_intra = (
                    "You are summarizing the current state of a debate group.\n"
                    "They are solving:\n"
                    f"{question}\n\n"
                    "Here are all agents' current answers:\n"
                    f"{group_prev_text}\n\n"
                    "Please create a concise summary (max 150 words) that:\n"
                    "1. Captures the key reasoning points.\n"
                    "2. Notes any disagreements or consensus.\n"
                    "3. Includes the group's current answer in \\boxed{answer} format.\n"
                    "Keep it brief and focused."
                )
                
                summary_messages_intra = [
                    {
                        "role": "system",
                        "content": "You create concise summaries of group debate progress."
                    },
                    {
                        "role": "user",
                        "content": summary_prompt_intra
                    }
                ]
                
                completion_summary = client.chat.completions.create(
                    model=model,
                    messages=summary_messages_intra,
                    n=1,
                    temperature=temperature,
                )
                summary_msg_intra = construct_assistant_message(completion_summary)
                group_summary_text = summary_msg_intra["content"]
                
                # according to the paper: limit the length of the summary token (constant C, controlling token cost)
                group_summary_text = truncate_to_tokens(group_summary_text, max_summary_tokens, model)
                
                if s not in group_summaries_per_round:
                    group_summaries_per_round[s] = {}
                if r not in group_summaries_per_round[s]:
                    group_summaries_per_round[s][r] = {}
                group_summaries_per_round[s][r][g_idx] = group_summary_text
                
                # now each agent sees the summary, instead of the full output
                for agent_id in group:
                    user_content = (
                        "We are still solving the same math problem:\n"
                        f"{question}\n\n"
                        "Here is a summary of your group's current discussion:\n"
                        f"{group_summary_text}\n\n"
                        "Reflect on whether your previous answer was correct. "
                        "If you find mistakes, fix them. "
                        "Explain your reasoning briefly and then give your updated final answer "
                        "in the form \\boxed{answer} at the end."
                    )

                    messages = [
                        system_prompts[agent_id],
                        {"role": "user", "content": user_content}
                    ]

                    completion = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        n=1,
                        temperature=temperature,
                    )
                    assistant_message = construct_assistant_message(completion)
                    agent_messages[agent_id] = messages + [assistant_message]
                    agent_last_output[agent_id] = assistant_message["content"]

            # ---- Stage ends: each group generates a summary, put it into the summary pool ----
            # according to the paper: this summary is used for inter-group communication in the next stage
        # implement forgetfulness: only keep the latest summary, not keep the full history
        # limit the token: summary is limited to max_summary_tokens (constant C)
        group_summaries = {}
        for g_idx, group in enumerate(groups):
            # collect the final output of all agents in this group
            lines = []
            for agent_id in group:
                lines.append(
                    f"Agent #{agent_id}'s final answer in this stage:\n{agent_last_output[agent_id]}"
                )
            group_text = "\n\n".join(lines)

            summary_prompt = (
                "You are the summarizer of a debate group of math agents.\n"
                "They are solving the following problem:\n"
                f"{question}\n\n"
                "Here are all agents' final answers in this stage:\n"
                f"{group_text}\n\n"
                "Please create a concise summary that:\n"
                "1. Briefly summarizes the key reasoning shared by the group (max 100 words).\n"
                "2. Gives the group's final numeric answer in the form \\boxed{answer} at the end.\n"
                "Keep it brief and focused - this summary will be used by other groups in the next stage."
            )
            messages = [
                {
                    "role": "system",
                    "content": "You summarize the debate of a group of math agents. Keep summaries concise."
                },
                {
                    "role": "user",
                    "content": summary_prompt
                }
            ]

            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                n=1,
                temperature=temperature,
            )
            summary_msg = construct_assistant_message(completion)
            raw_summary = summary_msg["content"]
            
            # limit the length of the summary token (constant C in the paper)
            truncated_summary = truncate_to_tokens(raw_summary, max_summary_tokens, model)
            group_summaries[g_idx] = truncated_summary

        stage_summaries[s] = group_summaries

    # ===== 4. the output of the entire GroupDebate / majority voting =====
    # here we can take the majority vote of the final answers of all agents
    final_answers = []
    for agent_id in range(M):
        text = agent_last_output[agent_id]
        ans = extract_boxed_number(text)
        final_answers.append(ans)

    # majority voting (very naive counting)
    counts = {}
    for a in final_answers:
        if a is None:
            continue
        counts[a] = counts.get(a, 0) + 1
    if counts:
        final_answer = max(counts.items(), key=lambda x: x[1])[0]
    else:
        final_answer = None

    # build the format expected by eval_gsm.py: responses is [[messages1], [messages2], ...]
    agent_responses = []
    for agent_id in range(M):
        agent_responses.append(agent_messages[agent_id])
    
    return {
        "agent_outputs": agent_last_output,   # the final text answer of each agent
        "stage_summaries": stage_summaries,   # the summary of each group in each stage
        "final_answer": final_answer,         # the content of the \\boxed{...} in the majority voting
        "raw_final_answers": final_answers,   # the boxed answer extracted from each agent
        "agent_responses": agent_responses,   # the full message history of each agent (for eval_gsm.py)
    }

if __name__ == "__main__":

    random.seed(0)
    np.random.seed(0)

    os.makedirs("results", exist_ok=True)

    output_file = "results/gsm_groupdebate.json"

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

    for data in tqdm(questions):
        question = data['question']
        answer = data['answer']

        if question in generated_description:
            continue

        try:
            debate_result = run_group_debate(
                question=question,
                client=client,
                model="gpt-3.5-turbo",
                M=6,                # total number of agents
                group_sizes=[2, 2, 2],  # 3 个 group，每组 2 个 agent
                S=2,                # number of stages
                R=2,                # number of intra-group rounds in each stage
                temperature=0.0,
                max_summary_tokens=200,  # limit the length of the summary token (constant C in the paper)
            )

            # save the format expected by eval_gsm.py: [responses, gt]
            # responses is [[messages1], [messages2], ...] format, each messages is the full conversation history of an agent
            generated_description[question] = [
                debate_result["agent_responses"],  # responses: [[messages1], [messages2], ...]
                answer  # gt: ground truth answer
            ]

            with open(output_file, "w") as f:
                json.dump(generated_description, f, indent=2)

        except Exception as e:
            print(f"\nError processing question: {e}")
            print(f"Progress saved. {len(generated_description)} questions completed.")
            with open(output_file, "w") as f:
                json.dump(generated_description, f, indent=2)
            raise

    print(f"\nCompleted! Total: {len(generated_description)} questions saved to {output_file}")