import subprocess

def run():
    res_status = subprocess.run(["git", "status"], capture_output=True, text=True, encoding="utf-8")
    res_name_status = subprocess.run(["git", "diff", "7c8d721", "HEAD", "--name-status"], capture_output=True, text=True, encoding="utf-8")
    res_diff = subprocess.run(["git", "diff", "7c8d721", "HEAD"], capture_output=True, text=True, encoding="utf-8")
    
    with open("diff_output.txt", "w", encoding="utf-8") as f:
        f.write("=== GIT STATUS ===\n")
        f.write(res_status.stdout)
        f.write("\n=== GIT DIFF --NAME-STATUS ===\n")
        f.write(res_name_status.stdout)
        f.write("\n=== GIT DIFF ===\n")
        f.write(res_diff.stdout)

if __name__ == "__main__":
    run()
