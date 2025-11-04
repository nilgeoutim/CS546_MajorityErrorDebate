## 🔬 Project Core Methodology: Robust MAD Framework with Multi-Dimensional Scoring (Code Implementation Details Enhanced)

This research aims to address the **Majority Error Problem** in Multi-Agent Debate (MAD) by introducing a **Critic-Actor Architecture** focused on **mathematical reasoning tasks**.

### 1. Core Architecture and Role Specialization (Implementation of Role-Playing)

The framework utilizes a **Critic-Actor** architecture, achieving role separation through carefully designed Llama model prompts.

#### 1.1. Actor Agents

| Phase | Function/Prompt | Role Definition and Objective |
| :--- | :--- | :--- |
| **Initial Solution (Round 1)** | `construct_actor_prompt(question)`: Includes **"Can you solve the following math problem? ... Let's think step by step."** | Employs a standard Chain of Thought (CoT) prompt, urging the Agent to act as a **"Solver"** and produce detailed reasoning. |
| **Debate Reflection (Round 2)** | `construct_debate_prompt(...)`: Includes **"You are a debater in a multi-agent debate..."** | The Agent transitions from "Solver" to **"Debater"**, receiving its own and all other Agents' **scored solutions** for comprehensive evaluation. |

#### 1.2. Critic Agents

* **Responsibility:** To evaluate the **Actor's solutions** and provide **multi-dimensional confidence scores**.
* **Function:** `construct_critic_prompt(question, solution)` explicitly assigns the role: **"You are a Critic agent. Your task is to evaluate a given solution..."**
* **Role Separation:** This design prevents the Critic from falling into the "criticism for criticism's sake" trap, focusing it instead on **objective assessment**.

### 2. Multi-Dimensional Confidence and Robust Scoring (Score Generation & Robustness)

This is the key mechanism designed to mitigate the Majority Error Problem.

#### 2.1. Score Generation and Format Constraints

* **Multi-Dimensional Scoring:** The Critic Agent is strictly required to output the two dimension scores you designed: `logic_score` and `computation_score`.
* **Format Requirement:** The prompt demands that the model provide a **single JSON object** containing the keys: `'logic_score'`, `'computation_score'`, and `'critique'`, enforced by the instruction **"Your response MUST be only the JSON object."**

#### 2.2. Robust Score Parsing

* **Function:** `parse_critic_output(text)` ensures the system's operational stability.
* **Loose Extraction:** Uses regular expressions (`re.search(r'\{.*\}', text, re.DOTALL)`) to **locate and extract** the JSON content within the Llama's full output, handling "dirty data" where the model may add extra text outside the JSON structure.
* **Safe Access:** Employs safe dictionary access methods like `data.get('logic_score', 0)` to ensure that if a critical scoring key is missing, the program returns a default value of `0` instead of crashing.

### 3. Adaptive Threshold and Llama Model Parameter Optimization (Adaptive Threshold & Parameter Usage)

The framework achieves efficiency and robustness through precise control over Llama model parameters. The use of the Adaptive Threshold directly addresses the issues of **"Cognitive Tunneling"** and **"Role Rigidity"**—which are documented roots of the Majority Error Problem.

#### 3.1. Implementation of Adaptive Threshold

* **Core Instructions:** The Adaptive Threshold is realized by leveraging the Llama model's own reasoning capabilities within the debate prompt:
    * **Defend:** **"If you believe your original solution is correct... defend it."**
    * **Adopt:** **"If you find another agent's solution is demonstrably better (based on its high logic/computation scores... adopt its reasoning."**
* **Objective:** This forces Actors to make rational decisions based on **scored evidence**, allowing them to change their mind only when the $S_{Logic}$ and $S_{Comp}$ scores are demonstrably superior, thus protecting correct minority opinions.

#### 3.2. Model Parameter Optimization

| Role | Key Parameters | Objective |
| :--- | :--- | :--- |
| **Actor/Debater** | `do_sample=True`, `temperature=0.7`, `top_p=0.9` | **Encourage Diversity:** Promotes the generation of diverse solutions and thought paths among Agents. |
| `max_new_tokens=1024` | Ensures sufficient token space for detailed "Let's think step by step" reasoning. |
| **Critic** | `do_sample=False` | **Seek Determinism/Objectivity:** Forces the model to use greedy search, ensuring the scores are stable and objective across identical inputs. |
| `max_new_tokens=256` | Speeds up inference and conserves resources, as only a short JSON object is required. |
| **General** | `eos_token_id=terminators` | Uses the Llama instruction model's specific End-of-Turn (EOT) token to prevent the model from generating unnecessary text after the required response, ensuring efficiency. |
### 5. Running the Experiment (Execution Plan)
The experiment is divided into two parts: generation and evaluation, using the Llama 3.1 8B Instruct model

**Command:** `python gen_math_critic_actor.py` 

**Process:** This script will load the Llama 3.1 8B Instruct model, process 100 questions from `gsm_test.jsonl`.

**Expected Output:** A detailed JSON file containing solutions and scores for all rounds: `gsm_critic_actor_3_2.json`.

#### 5.2. Run Evaluation 

**Command:** `python eval_math_critic_actor.py`

**Process:** This script will load the generated JSON file, parse the final debate round answers from all Agents, calculate the majority vote, compare it against the gold standard answer, and report the overall accuracy.