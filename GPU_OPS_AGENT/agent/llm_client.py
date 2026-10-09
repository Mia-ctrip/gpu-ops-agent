import llm_config
import time
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




# 大模型调用
def llm_call(messages, tools, client, model_name)->object:
    try:
        if tools is None:
            response =  client.chat.completions.create(
                        model = model_name,
                        messages = messages
                    )
        else:    
            response =  client.chat.completions.create(
                model = model_name,
                messages = messages,
                tools = tools,
                tool_choice="auto"
            )
        return response
    except RateLimitError as e:
        print("429:", e)
        return "continue"
    except AuthenticationError as e:
        print("401:", e)
        return "break"
    except BadRequestError as e:
        print("400:", e)
        return "break"
    except NotFoundError as e:
        print("404:", e)
        return "break"
    except InternalServerError as e:
        print("500:", e)
        raise Exception("service error")
    except Exception as e:
        print("unknow:",e)
        raise Exception("service error")


#模型降级
def call_link()->list:
    return [
        {
            "model_name":"deepseek-v4-flash" ,
            "model_supplier" :"DEEP_SEEK"
        },
        {
            "model_name":"deepseek-v4-pro" ,
            "model_supplier" :"DEEP_SEEK"
        },
        {
            "model_name":"MiniMax-M2.7" ,
            "model_supplier" :"MINI_MAX"
        }
    ]
    


#llm client调用入口
def client_call(messages,tools)->any:
    model_list = call_link()
    response = None
    #按照模型降级的调用链
    try:
        for model in model_list:
            model_name = model["model_name"]
            model_supplier = model["model_supplier"]
            api_key,base_url = llm_config.get(model_name,model_supplier)
            model_client = create_client(api_key,base_url)
            for i in range(llm_config.RETRY_TIMES):
                time.sleep(0.5)
                response = llm_call(messages,tools,model_client,model_name)
                if response == "break":
                    break
                elif response == "continue":
                    continue
                else:
                    return response.choices[0].message
    except Exception as e:
        raise Exception("llm calling fail")   

                
