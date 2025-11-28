import json
import numpy as np
import re

def solve_math_problems(input_str):
    pattern = r"\d+\.?\d*"
    matches = re.findall(pattern, input_str)
    if matches:
        return matches[-1]
    return None

def parse_answer(input_str):
    pattern = r"\{([0-9.,$]*)\}"
    matches = re.findall(pattern, input_str)
    
    solution = None
    for match_str in matches[::-1]:
        solution = re.sub(r"[^0-9.]", "", match_str)
        if solution:
            break
    
    return solution

def compute_accuracy(gt, pred_solution):
    answers = solve_math_problems(gt)
    
    if answers is None:
        return None
    
    if type(pred_solution) == list:
        pred_answers = []
        for pred_sol in pred_solution:
            pred_answer = parse_answer(pred_sol)
            if pred_answer is None:
                pred_answer = solve_math_problems(pred_sol)
            pred_answers.append(pred_answer)
        
        pred_answer = most_frequent(pred_answers)
    else:
        pred_answer = parse_answer(pred_solution)
        if pred_answer is None:
            pred_answer = solve_math_problems(pred_solution)
    
    if pred_answer is None:
        return 0
    
    if float(answers) == float(pred_answer):
        return 1
    else:
        return 0

def most_frequent(List):
    counter = 0
    num = List[0]
    
    for i in List:
        current_frequency = List.count(i)
        if current_frequency > counter:
            counter = current_frequency
            num = i
    
    return num

def read_jsonl(path: str):
    with open(path) as fh:
        return [json.loads(line) for line in fh.readlines() if line]

if __name__ == "__main__":
    # 读取生成的结果文件
    agents = 1
    rounds = 1
    response_dict = json.load(open("gsm_1_1_all.json".format(agents, rounds), "r"))
    
    # 读取原始测试文件，用于保存完整的问题信息
    original_questions = read_jsonl("gsm_test.jsonl")
    question_to_data = {data['question']: data for data in original_questions}
    
    questions = list(response_dict.keys())
    accuracies = []
    wrong_questions = []
    
    print("开始评估问题...")
    for i, question in enumerate(questions):
        responses, gt = response_dict[question]
        
        pred_solutions = []
        for response in responses:
            pred_solution = response[-1]['content']
            pred_solutions.append(pred_solution)
        
        accurate = compute_accuracy(gt, pred_solutions)
        
        if accurate is not None:
            accuracies.append(float(accurate))
            # 如果答错了（accurate == 0），保存这个问题
            if accurate == 0:
                if question in question_to_data:
                    wrong_questions.append(question_to_data[question])
                else:
                    # 如果找不到原始数据，至少保存问题和答案
                    wrong_questions.append({"question": question, "answer": gt})
        else:
            print(f"警告: 问题 {i+1} 无法计算准确率，GT: {gt}")
        
        # 每处理100个问题打印一次进度
        if (i + 1) % 100 == 0:
            current_acc = np.mean(accuracies) if accuracies else 0
            print(f"已处理 {i+1}/{len(questions)} 个问题，当前准确率: {current_acc:.4f}, 错误题目数: {len(wrong_questions)}")
    
    # 打印最终统计
    final_acc = np.mean(accuracies) if accuracies else 0
    final_std = np.std(accuracies) / (len(accuracies) ** 0.5) if accuracies else 0
    print(f"\n最终统计:")
    print(f"总问题数: {len(questions)}")
    print(f"准确率: {final_acc:.4f} ± {final_std:.4f}")
    print(f"错误题目数: {len(wrong_questions)}")
    
    # 保存错误题目到 gsm_hard.jsonl
    with open("gsm_hard_full.jsonl", "w") as f:
        for item in wrong_questions:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    print(f"\n已保存 {len(wrong_questions)} 个错误题目到 gsm_hard_full.jsonl")

