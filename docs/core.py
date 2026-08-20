import random
def generate_random_text():    length = random.randint(1, 100)    chars = 'abcdefghijklmnopqrstuvwxyz'    return ''.join(random.choice(chars) for _ in range(length))
random_text = generate_random_text()
print(f"Random text: {random_text}")