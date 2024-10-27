#!/usr/bin/env python3
import json
import os
import requests
import sys
from threading import Thread
from queue import Queue
from typing import List, Dict
from rich.console import Console
from rich.markdown import Markdown

STATUS_URL = "https://duckduckgo.com/duckchat/v1/status"
CHAT_URL = "https://duckduckgo.com/duckchat/v1/chat"
TERMS_OF_SERVICE_URL = "https://duckduckgo.com/aichat/privacy-terms"
CONFIG_FILE_PATH = "config.json"

class Model:
    GPT4Mini = "gpt-4o-mini"
    Claude3 = "claude-3-haiku-20240307"
    Llama = "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
    Mixtral = "mistralai/Mixtral-8x7B-Instruct-v0.1"

model_map = {
    "gpt-4o-mini": Model.GPT4Mini,
    "claude-3-haiku": Model.Claude3,
    "llama": Model.Llama,
    "mixtral": Model.Mixtral,
}

class Message:
    def __init__(self, content: str, role: str):
        self.content = content
        self.role = role

class ChatPayload:
    def __init__(self, model: str, messages: List[Message]):
        self.model = model
        self.messages = messages

class Chat:
    def __init__(self, vqd: str, model: str):
        self.old_vqd = vqd
        self.new_vqd = vqd
        self.model = model
        self.messages = []
        self.client = requests.Session()

    def fetch(self, content: str):
        self.messages.append(Message(content, "user"))
        payload = ChatPayload(self.model, self.messages)
        json_payload = json.dumps(payload, default=lambda o: o.__dict__)

        headers = {
            "x-vqd-4": self.new_vqd,
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
        }

        response = self.client.post(CHAT_URL, data=json_payload, headers=headers)

        if response.status_code != 200:
            raise Exception(f"{response.status_code}: Failed to send message. {response.reason}. Body: {response.text}")

        return response

    def fetch_stream(self, content: str):
        response = self.fetch(content)
        stream = Queue()

        def stream_response():
            text = ""
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data: "):
                        data = line[6:]
                        message_data = json.loads(data)
                        if message_data.get("message"):
                            text += message_data["message"]
                            stream.put(message_data["message"])
            self.old_vqd = self.new_vqd
            self.new_vqd = response.headers.get("x-vqd-4")
            self.messages.append(Message(text, "assistant"))
            stream.put(None)

        Thread(target=stream_response).start()
        return stream

    def redo(self):
        self.new_vqd = self.old_vqd
        if len(self.messages) >= 2:
            self.messages = self.messages[:-2]

def init_chat(model: str):
    headers = {"x-vqd-accept": "1"}
    response = requests.get(STATUS_URL, headers=headers)

    if response.status_code != 200:
        raise Exception(f"{response.status_code}: Failed to initialize chat. {response.reason}")

    vqd = response.headers.get("x-vqd-4")
    if not vqd:
        raise Exception("Failed to get VQD from response headers")

    return Chat(vqd, model_map[model])

def accept_terms_of_service():
    print(f"Please read and accept the terms of service at {TERMS_OF_SERVICE_URL}")
    while True:
        input_str = input("Do you accept the terms of service? (yes/no): ").strip().lower()
        if input_str in ["yes", "y"]:
            return True
        elif input_str in ["no", "n"]:
            return False

def load_config():
    if not os.path.exists(CONFIG_FILE_PATH):
        print("Config file does not exist. Returning empty config.")
        return {}

    with open(CONFIG_FILE_PATH, 'r') as file:
        config = json.load(file)
        return config

def save_config(config: Dict):
    try:
        print(f"Saving config: {config}")
        with open(CONFIG_FILE_PATH, 'w') as file:
            json.dump(config, file)
        print("Config saved successfully.")
    except Exception as e:
        print(f"Failed to save config file: {e}")

def sanitize_input(input_str: str):
    return input_str.replace("\"", "").replace("=", "")

def choose_model():
    print("Choose a model:")
    print("1. GPT-4o Mini")
    print("2. Claude 3 Haiku")
    print("3. Llama")
    print("4. Mixtral")
    while True:
        choice = input("Enter the number of your choice: ").strip()
        if choice in ["1", "2", "3", "4"]:
            return ["gpt-4o-mini", "claude-3-haiku", "llama", "mixtral"][int(choice) - 1]
        print("Invalid choice. Please enter a number between 1 and 4.")

def print_response(stream: Queue):
    console = Console()
    buffer = ""
    while True:
        chunk = stream.get()
        if chunk is None:
            break
        buffer += chunk

    markdown_content = Markdown(buffer)
    console.print(markdown_content)


def main():
    try:
        config = load_config()

        if not config.get("accepted_terms"):
            if not accept_terms_of_service():
                return
            config["accepted_terms"] = True
            save_config(config)

        model = config.get("default_model")
        if not model:
            model = choose_model()
            config["default_model"] = model
            save_config(config)

        chat = init_chat(model)

        initial_prompt = ""
        if len(sys.argv) > 1:
            initial_prompt = sanitize_input(" ".join(sys.argv[1:]))

        if initial_prompt:
            stream = chat.fetch_stream(initial_prompt)
            print("\033[1;32mAI:\033[0m ")  
            print_response(stream)

        while True:
            input_str = input("\033[1;34mYou:\033[0m ").strip()  
            if input_str == "exit":
                break
            stream = chat.fetch_stream(input_str)
            print("\033[1;32mAI:\033[0m ")  
            print_response(stream)
    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()
