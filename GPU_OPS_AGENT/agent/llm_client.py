from config import *
from openai import (
    OpenAI,
    APIError,
    APIConnectionError, 
    APIStatusError,
    BadRequestError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    UnprocessableEntityError,
    RateLimitError,
    InternalServerError,
)



def create_client(api_key: str, base_url: str | None = None) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=base_url
    )


class LlmInput():
    def __init__(self,system_prompt,user_message,tools)->None:
        self.system_prompt = system_prompt
        self.user_message = user_message


# 大模型调用
def llm_call(llm_input, tools, client, model_name)->object:
    system_prompt = llm_input.system_prompt
    user_message = llm_input.user_message
    try:
        response =  client.chat.completions.create(
            model = model_name,
            instructions = system_prompt,
            input = [
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            tools = tools,
            tool_choice="auto"
        )
        return response
    except RateLimitError as e:
        print("429:", e)
        return "break"
    except AuthenticationError as e:
        print("401:", e)
        return "break"
    except BadRequestError as e:
        print("400:", e)
        return "continue"
    except NotFoundError as e:
        print("404:", e)
        return "break"
    except InternalServerError as e:
        print("500:", e)
        raise Exception("service error")
    except Exception as e
        print("unknow:",e)
        raise Exception("service error")


#模型降级
def call_link()->list:
    return [
        {
            "model_name":"deepseek v4 pro" ,
            "model_supplier" :"DEEP_SEEK"
        },
        {
            "model_name":"deepseek v4 flush" ,
            "model_supplier" :"DEEP_SEEK"
        },
        {
            "model_name":"minimax m3" ,
            "model_supplier" :"MINI_MAX"
        }
    ]
    


#llm client调用入口
def client_call(model_input)->list:
    tools = 
    model_list = call_link()
    #按照模型降级的调用链
    try:
        for model in model_list:
            model_name = model["model_name"]
            model_supplier = model["model_supplier"]
            api_key,base_url = config.get(model_name,model_supplier)
            model_client = create_client(api_key,base_url)
            for i in range(config.RETRY_TIMES):
                response = llm_call(model_input,tools,model_client,model_name)
                if response == "break":
                    break
                elif response == "continue":
                    continue
    except Exception as e:
        raise Exception("llm calling fail")            
                
