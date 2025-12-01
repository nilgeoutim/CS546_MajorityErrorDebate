import json
import openai
import random
from tqdm import tqdm

def parse_bullets(sentence):
    bullets_preprocess = sentence.split("\n")
    bullets = []

    for bullet in bullets_preprocess:
        try:
            idx = bullet.find(next(filter(str.isalpha, bullet)))
        except:
            continue

        bullet = bullet[idx:]

        if len(bullet) != 0:
            bullets.append(bullet)

    return bullets


def filter_people(person):
    people = person.split("(")[0]
    return people


def construct_assistant_message(completion):
    content = completion.choices[0].message.content
    return {"role": "assistant", "content": content}


if __name__ == "__main__":
    with open("article.json", "r") as f:
        data = json.load(f)

    people = sorted(data.keys())
    people = [filter_people(person) for person in people]
    random.seed(1)
    random.shuffle(people)

    generated_description = {}

    client = openai.OpenAI()
    
    for person in tqdm(people[:40]):
        # Single direct request without discussion
        messages = [{"role": "user", "content": "Give a bullet point biography of {} highlighting their contributions and achievements as a computer scientist, with each fact separated with a new line character. ".format(person)}]
        
        try:
            completion = client.chat.completions.create(
                      model="gpt-3.5-turbo-0301",
                      messages=messages,
                      n=1,
                      temperature=0,
                      top_p=1)
        except:
            completion = client.chat.completions.create(
                      model="gpt-3.5-turbo-0301",
                      messages=messages,
                      n=1,
                      temperature=0,
                      top_p=1)

        print(completion)
        assistant_message = construct_assistant_message(completion)
        messages.append(assistant_message)

        generated_description[person] = messages

    json.dump(generated_description, open("biography_baseline.json", "w"))

