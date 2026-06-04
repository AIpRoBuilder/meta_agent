from openai import OpenAI

client = OpenAI(
    api_key="d3364ef47a8f43d1997bea7b69bd664f",
    base_url="https://dsjai.xin/v1",
)

response = client.chat.completions.create(
    model="gpt-5.4-mini",
    messages=[
        {"role": "system", "content": "你是一个可靠的企业助手。"},
        {"role": "user", "content": "用三句话总结 D-API 的接入方式。"},
    ],
)

print(response.choices[0].message.content)