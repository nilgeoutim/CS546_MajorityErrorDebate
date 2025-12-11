#!/bin/bash

# 运行 GSM v4 生成脚本
# 使用方法: ./run_gsm_v4.sh [options]

# 默认参数
AGENTS=3
ROUNDS=3
SAMPLE_COUNT=100
INPUT_FILE="gsm_test.jsonl"
SEED=0
HIGH_THRESHOLD=5
LOW_THRESHOLD=7
PRINT_HYPERPARAMS=false

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --agents)
            AGENTS="$2"
            shift 2
            ;;
        --rounds)
            ROUNDS="$2"
            shift 2
            ;;
        --sample_count)
            SAMPLE_COUNT="$2"
            shift 2
            ;;
        --input_file)
            INPUT_FILE="$2"
            shift 2
            ;;
        --seed)
            SEED="$2"
            shift 2
            ;;
        --high_threshold)
            HIGH_THRESHOLD="$2"
            shift 2
            ;;
        --low_threshold)
            LOW_THRESHOLD="$2"
            shift 2
            ;;
        --print_hyperparams)
            PRINT_HYPERPARAMS=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --agents NUM              Number of agents (default: 3)"
            echo "  --rounds NUM               Number of debate rounds (default: 3)"
            echo "  --sample_count NUM         Number of samples to process (default: 100)"
            echo "  --input_file FILE          Input JSONL file (default: gsm_test.jsonl)"
            echo "  --seed NUM                 Random seed (default: 0)"
            echo "  --high_threshold NUM       High confidence threshold (default: 5)"
            echo "  --low_threshold NUM        Low confidence threshold (default: 7)"
            echo "  --print_hyperparams        Print hyperparameters before running"
            echo "  -h, --help                Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# 构建命令
CMD="python gen_gsm_confiscore_v4.py"
CMD="$CMD --agents $AGENTS"
CMD="$CMD --rounds $ROUNDS"
CMD="$CMD --sample_count $SAMPLE_COUNT"
CMD="$CMD --input_file $INPUT_FILE"
CMD="$CMD --seed $SEED"
CMD="$CMD --high_threshold $HIGH_THRESHOLD"
CMD="$CMD --low_threshold $LOW_THRESHOLD"

if [ "$PRINT_HYPERPARAMS" = true ]; then
    CMD="$CMD --print_hyperparams"
fi

# 执行命令
echo "Running: $CMD"
echo ""
eval $CMD




