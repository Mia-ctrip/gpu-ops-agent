from llm_client import client_call, LlmInput


if __name__ == "__main__":
    llm_input = LlmInput("你是一个NBA领域的资深专家，关注NBA新闻，非常了解NBA联盟的劳资协议和CBA协议以及各项章程。要求你在回复用户问题时在给出结论和分析的同时需要给出相应的劳资协议条款或者其他有力依据作为佐证。",
    "请你帮我分析文班亚马续约合同的理论顶薪是多少美元？")
    output = client_call(llm_input)
    print(output)