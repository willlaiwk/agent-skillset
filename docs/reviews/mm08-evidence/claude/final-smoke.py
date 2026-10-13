def greeting(name):
    name = name.strip()
    if not name:
        raise ValueError("name is required")
    return f"Hello, {name}!"
