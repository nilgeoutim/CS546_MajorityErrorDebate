# Majority Errors in Multi-Agent Debate: Analysis and Framework Design

### [Project Paper](./CS546_GP.pdf) | [Original Framework](https://github.com/composable-models/llm_multiagent_debate)

[Meitong Liu](mailto:meitong4@illinois.edu),
[Maojie Xu](mailto:maojiex2@illinois.edu),
[Jieyi Zhao](mailto:jieyi3@illinois.edu),
[Ian Jiang](mailto:jisheng3@illinois.edu),
[Wangjia Zhan](mailto:wangjia2@illinois.edu)

This project investigates a critical limitation of Multi-Agent Debate (MAD): the **"majority error"** setting, where the majority of agents initially produce incorrect answers. Our analysis reveals that naive MAD often fails to recover from these errors, with performance gains stemming primarily from increased sampling rather than the debate process itself.

To address this, we propose two extensions to stabilize debate and improve reasoning:
1.  **Confidence Score:** Incorporating an external critic to assign confidence scores.
2.  **Role Specialization:** Introducing diverse roles (Logician, Programmer, Skeptic) to reduce correlated errors.
![Framework Workflow](framework_workflow.png)
## Running experiments

The code for running our majority-error analysis and improved debate frameworks can be found in the `gsm/` folder. 
### Dataset setup:
1. gsm_test.jsonl: the original GSM_8k
2. gsm_majority_error.jsonl: A challenging subset of GSM8K. We extract 225 questions from the test set where a majority vote among three independently sampled agents is incorrect

### Run Experiments

**Naive MAD Analysis:**

To generate answers using the standard Multi-Agent Debate baseline and analyze performance on majority-error tasks:
    
    cd gsm
    python gen_gsm.py

To evaluate the generated results and compute flip statistics:
    
    python eval_gsm.py

**Improved Frameworks (Ours):**

To run the multi-agent debate with our proposed **Confidence Score** (§3.1), use the following scripts:

    python gen_gsm_confiscore_v1.py  # v1: Local-View Critic
    python gen_gsm_confiscore_v2.py  # v2: Global-View Critic (Paper Implementation)

Version Differences: Version 1 (Local View): The critic evaluates each agent individually; Version 2 (Global View): The critic assesses all agents simultaneously to resolve conflicts and mitigate collective hallucinations. Note: While Version 2 is the primary method presented in our paper, we include Version 1 as it occasionally achieves superior performance in empirical trials.

To run the debate with our proposed **Role Specialization** (§3.2):
    
    python gen_gsm_role_specialization.py


To evaluate the potential of MAD under **High-Quality Supervision** (using a stronger critic, §5.5):

    python gen_gsm_better_supervision.py

The defalut settings of stronger critic used is GPT-5.1, which is also used in the evaluation process. This method is intended to discover the potential of MAD under the high-quality supervision. The stronger model will not provide direct answer, only justification and hints are provided to guide the converge.

**Visualization:**

To reproduce the analysis figures (Accuracy Trends, Flip Dynamics) shown in the report:

    jupyter notebook Figures.ipynb

## Citation

If you use this code or analysis in your work, please cite our project:

```bibtex
@article{liu2025majority,
  title={Majority Errors in Multi-Agent Debate: Analysis and Framework Design},
  author={Liu, Meitong and Xu, Maojie and Zhao, Jieyi and Jiang, Ian and Zhan, Wangjia},
  journal={Course Project, CS546},
  year={2025}
}
