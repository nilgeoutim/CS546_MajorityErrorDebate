# Majority Errors in Multi-Agent Debate: Analysis and Framework Design

### [Project Paper](./CS546_GP.pdf) | [Original Framework](https://github.com/composable-models/llm_debate)

[Meitong Liu](mailto:meitong4@illinois.edu),
[Maojie Xu](mailto:maojiex2@illinois.edu),
[Jieyi Zhao](mailto:jieyi3@illinois.edu),
[Ian Jiang](mailto:jisheng3@illinois.edu),
[Wangjia Zhan](mailto:wangjia2@illinois.edu)

This project investigates a critical limitation of Multi-Agent Debate (MAD): the **"majority error"** setting, where the majority of agents initially produce incorrect answers. Our analysis reveals that naive MAD often fails to recover from these errors, with performance gains stemming primarily from increased sampling rather than the debate process itself.

To address this, we propose two extensions to stabilize debate and improve reasoning:
1.  **Confidence Score:** Incorporating an external critic to assign confidence scores.
2.  **Role Specialization:** Introducing diverse roles (Logician, Programmer, Skeptic) to reduce correlated errors.

## Running experiments

The code for running our majority-error analysis and improved debate frameworks can be found in the `gsm/` folder. We focus on a challenging subset of GSM8K where standard majority voting fails.

**Naive MAD Analysis:**

To generate answers using the standard Multi-Agent Debate baseline and analyze performance on majority-error tasks:
    
    cd gsm
    python gen_gsm.py

To evaluate the generated results and compute flip statistics:
    
    python eval_gsm.py

**Improved Frameworks (Ours):**

To run the debate with our proposed **Confidence Score** and **Role Specialization** :

    python gen_gsm_confiscore_v5.py

To evaluate the potential of MAD under **High-Quality Supervision** (using a stronger critic):

    python gen_gsm_better_supervision.py

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
