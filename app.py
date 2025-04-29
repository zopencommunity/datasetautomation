import subprocess
import os
import shutil
import glob
import time
import re
import json
import argparse
from pathlib import Path


# function to clone the repository
def clonning_the_repo(clone_link,destination_dir):
    try:
        # Construct the git clone command
        result = subprocess.run(
            ['git', 'clone', clone_link, destination_dir],
            check=True,             # Raises CalledProcessError if the command fails
            stdout=subprocess.PIPE,  # Capture standard output
            stderr=subprocess.PIPE   # Capture standard error
        )
        return f"Repository cloned successfully to {destination_dir}!"
    except subprocess.CalledProcessError as e:
        return f"Error occurred while cloning the repository:\n{e.stderr.decode()}"
    except FileNotFoundError:
        return "Git is not installed or not found in your system PATH."

# check if the build type is stable
def check_if_stable(buildenv_path):
    try:
        with open(buildenv_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        if 'STABLE' in content:
            return 'stable'
    except Exception as e:
        print(f"⚠️ Could not read buildenv: {e}")
    return 'unknown'


# function to move the patches outside to temporary folder
# the patches of the type *.h.patch or *.c.patch is only moved out as we consider
# others to be functionality patches
def moveout_patches(destination):
    patch_type = check_if_stable(destination + "/buildenv")

    if patch_type == "stable":
        fallback_dir = "/data/students/Automation/temp/patches"
        preferred_dir = "/data/students/Automation/temp/stable-patches"

        source_dir = preferred_dir if os.path.exists(preferred_dir) else fallback_dir
        destination_dir = "/data/students/Automation/patches"
        moved_files = []

        for filename in os.listdir(source_dir):
            if filename.endswith(".c.patch") or filename.endswith(".h.patch"):
                source_path = os.path.join(source_dir, filename)
                destination_path = os.path.join(destination_dir, filename)

                # Avoid moving if already in destination
                if os.path.abspath(source_path) != os.path.abspath(destination_path):
                    shutil.move(source_path, destination_path)
                    moved_files.append(filename)

        if moved_files:
            print("✅ Moved the following patch files:")
            for f in moved_files:
                print(f" - {f}")
        else:
            print("ℹ️ No .c.patch or .h.patch files found in:", source_dir)

def run_zopen_build_and_capture_logs(build_dir):
    print("🚀 Running 'zopen build -vv' in:", build_dir)

    try:
        result = subprocess.run(
            ["zopen", "build", "-vv"],
            cwd=build_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='ignore'  # Ignore problematic characters instead of crashing
        )
    except Exception as e:
        print(f"❌ Failed to run zopen build: {e}")
        return

    print("⏳ Waiting for log file to be written...")
    time.sleep(2)

    # Find latest *_build.log
    log_pattern = os.path.join(build_dir+"/log.STABLE", "*_build.log")
    log_files = glob.glob(log_pattern)
    if not log_files:
        print("❌ No build log files found.")
        return

    latest_log = max(log_files, key=os.path.getmtime)
    print(f"📄 Found latest log file: {latest_log}")
    pattern = os.path.join("/data/students/Automation/temp/log.STABLE", "*_check.log")
    matched_files = glob.glob(pattern)
    if matched_files:
        print("✅ The tool is built without any errors")
        return False
    # Save log content
    temp_log_path = os.path.join(build_dir, "temp_build_error.log")
    try:
        with open(latest_log, "r", encoding='utf-8', errors='ignore') as f:
            log_content = f.read()
        with open(temp_log_path, "w", encoding='utf-8') as temp_file:
            temp_file.write(log_content)
        print(f"✅ Log content saved to: {temp_log_path}")
    except Exception as e:
        print(f"❌ Error reading/writing log: {e}")

    # Remove log.STABLE
    log_stable_path = os.path.join(build_dir, "log.STABLE")
    if os.path.isdir(log_stable_path):
        shutil.rmtree(log_stable_path)
        print(f"🧹 Removed directory: {log_stable_path}")
    else:
        print("ℹ️ 'log.STABLE' directory not found, nothing to delete.")



def check_build_log_for_errors(log_dir):
    try:
        # Specify the log file path
        log_file = os.path.join(log_dir, "temp_build_error.log")
        
        # Ensure the file exists
        if not os.path.exists(log_file):
            print(f"🔥 Log file does not exist: {log_file}")
            return "Log file not found"
        
        # Run the grep command
        command = ['grep', '-i', '-A', '3', 'error:', log_file]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            print("❌ Build failed with the following errors:")
            print(result.stdout)
            return result.stdout
        elif result.returncode == 1:
            print("✅ Build successful. No errors found.")
            print("Since no error is found checking if build is successful !!")
            
        else:
            print("⚠️ Grep encountered an unexpected issue:")
            print(result.stderr)
            return "FAIL"

    except Exception as e:
        print(f"🔥 An exception occurred: {e}")
        return "FAIL"


def source_folder_name_extractor(buildenv_path):
    """
    Extracts the tool-version folder name from the first *_VERSION assignment.
    Returns a string like 'jq-1.7.1'
    """
    try:
        with open(buildenv_path, 'r') as file:
            for line in file:
                match = re.match(r'([A-Z0-9_]+)_VERSION\s*=\s*[\'"](.+?)[\'"]', line)
                if match:
                    tool_name = match.group(1).lower()  # Convert TOOL_VERSION → tool
                    version = match.group(2)
                    return f"{tool_name}-{version}"
        print("⚠️ No *_VERSION assignment found in buildenv.")
        return None
    except FileNotFoundError:
        print(f"❌ File not found: {buildenv_path}")
        return None
    except Exception as e:
        print(f"🔥 Error while parsing buildenv: {e}")
        return None

def extract_wrong_code_and_correct_code_delete_source(error_message, source_folder_name):
    # Match paths like src/xyz.c, lib/xyz.h etc.
    match = re.search(r'(src|lib)/[a-zA-Z0-9_\-]+\.([ch])', error_message)
    
    if match:
        file_name = match.group(0)  # e.g. src/xyz.c
    else:
        print("🚫 Could not extract filename from the error message.")
        return None, None, None, False

    # Construct full file path
    file_path = os.path.join("/data/students/Automation/temp", source_folder_name, file_name)

    # Read the original content (wrong code)
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            wrong_code = file.read()
    except FileNotFoundError:
        print(f"❌ File not found: {file_path}")
        return None, None, None, False
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return None, None, None, False

    # Construct the patch file path (e.g., xyz.c.patch)
    base_name = os.path.basename(file_name)             # xyz.c
    patch_name = f"{base_name}.patch"                   # xyz.c.patch
    patch_path = os.path.join("/data/students/Automation/patches", patch_name)

    # Apply patch using subprocess
    try:
        patch_result = subprocess.run(
            ["patch", file_path, "-i", patch_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if patch_result.returncode != 0:
            print(f"⚠️ Failed to apply patch:\n{patch_result.stderr}")
            return wrong_code, None, file_name, False
    except Exception as e:
        print(f"❌ Exception while applying patch: {e}")
        return wrong_code, None, file_name, False

    # Read the patched (corrected) file content
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            corrected_code = file.read()
    except Exception as e:
        print(f"❌ Error reading corrected file: {e}")
        return wrong_code, None, file_name, False

    # Delete the folder
    folder_path = os.path.join("/data/students/Automation/temp", source_folder_name)
    try:
        delete_result = subprocess.run(["rm", "-rf", folder_path],
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       text=True)
        if delete_result.returncode == 0:
            print(f"✅ Folder '{folder_path}' deleted successfully.")
            return wrong_code, corrected_code, file_name, True
        else:
            print(f"⚠️ Error deleting folder: {delete_result.stderr}")
            return wrong_code, corrected_code, file_name, False
    except Exception as e:
        print(f"❌ Exception while deleting folder: {e}")
        return wrong_code, corrected_code, file_name, False

    
def move_and_read_patch_file(file_path: str, src_dir: str, dest_dir: str) -> tuple[str, bool]:
    """
    Takes a file path like 'src/filename.c', extracts 'filename.c', appends '.patch',
    moves it from src_dir to dest_dir, and returns its contents.

    Returns:
        (file_content, True) if success
        (None, False) if error
    """
    # Extract base name: 'filename.c' or 'filename.h'
    base_name = os.path.basename(file_path)

    # Append .patch => filename.c.patch
    patch_name = base_name + ".patch"

    # Construct full source and destination paths
    source_file_path = os.path.join(src_dir, patch_name)
    dest_file_path = os.path.join(dest_dir, patch_name)

    try:
        # Ensure destination directory exists
        os.makedirs(dest_dir, exist_ok=True)

        # Move the file
        shutil.move(source_file_path, dest_file_path)
        print(f"✅ Moved {source_file_path} ➡️ {dest_file_path}")

        # Read and return the content
        with open(dest_file_path, "r", encoding="utf-8") as file:
            content = file.read()

        return content, True

    except FileNotFoundError:
        print(f"❌ Patch file not found: {source_file_path}")
        return None, False
    except Exception as e:
        print(f"❌ Error: {e}")
        return None, False
        
def check_for_functionality_patches(directory_path):
        """
        Returns False if the directory is empty, True otherwise.
        Also prints the result.
        """
        try:
            if not os.path.exists(directory_path):
                print(f"❌ Directory does not exist: {directory_path}")
                return False

            if not os.path.isdir(directory_path):
                print(f"❌ Path is not a directory: {directory_path}")
                return False

            if len(os.listdir(directory_path)) == 0:
                print(f"✅ Directory is empty: {directory_path}")
                return False
            else:
                print(f"📁 Directory is NOT empty: {directory_path}")
                return True

        except Exception as e:
            print(f"🔥 Error checking directory: {e}")
            return False
        
def extract_patch_target(patch_path):
    """
    Extract the relative file path from a patch file.
    """
    with open(patch_path, 'r') as f:
        content = f.read()

    match = re.search(r'^diff --git a/(.*?) b/', content, re.MULTILINE)
    if match:
        return match.group(1)
    return None

def apply_patch(patch_file, source_dir):
    """
    Applies the given patch file to the corresponding file in the source directory.
    Collects:
        - wrong_code: file content before patch
        - correct_code: file content after patch
        - patch_code: contents of the patch file itself
    """
    relative_path = extract_patch_target(patch_file)
    if not relative_path:
        print(f"❌ Skipping {patch_file}: could not extract file path.")
        return False

    full_path = os.path.join(source_dir, relative_path)

    if not os.path.exists(full_path):
        print(f"📁 File {relative_path} not found in source dir. Skipping.")
        return False
    data={}
    data["error"]="Functionality Error"
    # Read and store original content
    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
        data["wrong_code"] = f.read()

    # Read and store the patch content
    with open(patch_file, 'r', encoding='utf-8', errors='ignore') as f:
        data["patch_code"] = f.read()

    try:
    # Apply the patch using updated subprocess format
        patch_result = subprocess.run(
            ["patch", full_path, "-i", patch_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if patch_result.returncode == 0:
            # Read and store new content after patch
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                data["correct_code"] = f.read()

            print(f"✅ Patch applied: {patch_file} and appended to the file")

            with open(f"/data/students/data/{source_folder_name}.jsonl", 'a', encoding='utf-8') as file:
                json_line = json.dumps(data)
                file.write(json_line + '\n')

            return True
        else:
            print(f"❌ Failed to apply patch: {patch_file}")
            print("stdout:", patch_result.stdout)
            print("stderr:", patch_result.stderr)
            return False

    except Exception as e:
        print(f"🚨 Unexpected error while applying patch: {patch_file}")
        print(str(e))
        return False
def capture_functionality_patches(patch_dir,source_dir):
    patch_dir = Path(patch_dir)
    patch_files = list(patch_dir.glob("*.patch")) + list(patch_dir.glob("*.diff"))

    for patch_file in patch_files:
        print(f"Applying {patch_file} patch")
        success = apply_patch(str(patch_file), source_dir)
        if success:
            os.remove(patch_file)
            print(f"🧹 Deleted patch: {patch_file}")
    
    print("Captured all the functionality patches . Exiting from the automation ")
    exit()

       

     
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clone a GitHub repo.")
    parser.add_argument("clone_link", help="GitHub repository clone link")
    
    args = parser.parse_args()
    clone_link = args.clone_link
    print("Clonning from the git hub \n")
    clonning_the_repo(clone_link,"/data/students/Automation/temp")
    print("Moving the patches to a temporary folder")
    moveout_patches("/data/students/Automation/temp")


    
    source_folder_name=source_folder_name_extractor("/data/students/Automation/temp/buildenv")
    if(source_folder_name==None):
        print("Could not find the source folder name \nEXITING FROM THE AUTOMATION")
        exit()
    with open(f"/data/students/data/{source_folder_name}.jsonl", 'w', encoding='utf-8') as file:
        pass
    print(f"✅ Created empty .jsonl file at: /data/students/data")
    
    while(True):
        data={}
        # build
        val=run_zopen_build_and_capture_logs("/data/students/Automation/temp")
        # checking if the build is completely successful
        if val==False:
            #check of there are functionality patches remaining
            is_fuctionality_patch=check_for_functionality_patches("/data/students/Automation/patches")
            if is_fuctionality_patch==True:
                print("--------------Capturing Functionality Patches--------------")
                capture_functionality_patches("/data/students/Automation/patches","/data/students/Automation/temp/"+source_folder_name)



        error=check_build_log_for_errors("/data/students/Automation/temp")
        if error=="FAIL":

            print("SOME KIND OF ERROR HAS OCCURED in FINDING ERROR FROM BUILD\nEXITING FROM THE AUTOMATION")
            exit()
        else:
            # store the error in a json
            data["error"]=error
        #applying a patch and copying the right code 

        # find the error file and then store the wrong code in json
        wrong_code,correct_code,file_name,check=extract_wrong_code_and_correct_code_delete_source(error,source_folder_name)
        if(check==False):
            print("SOME KIND OF ERROR HAS OCCURED IN EXTRACTING WRONG CODE\nEXITING FROM THE AUTOMATION")
            exit()
        else:
            data["wrong_code"]=wrong_code
            data["correct_code"]=correct_code
        
        src_dir = "/data/students/Automation/patches"
        dest_dir = "/data/students/Automation/temp/stable-patches"
        content, status = move_and_read_patch_file(file_name, src_dir, dest_dir)

        if status:
            data["patch_code"]=content
        else:
            print("🚫 Failed to move or read the patch file.")
            print("ERROR IN AUTOMATION \n EXITING ")
            exit()

        with open(f"/data/students/data/{source_folder_name}.jsonl", 'a', encoding='utf-8') as file:
            # Convert the dictionary to a JSON string and append it as a new line
            json_line = json.dumps(data)  # Convert the dictionary to a JSON string
            file.write(json_line + '\n')  # Write the JSON string followed by a newline
        

        
        
        

