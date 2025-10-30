#!/usr/bin/env python3

import os
import sys

def list_script_files():
    # Get all .py and .sh files excluding this script and files starting with '._'
    current_script = os.path.basename(__file__)
    script_files = [
        f for f in os.listdir('.')
        if (f.endswith('.py') or f.endswith('.sh'))
           and not f.startswith('._')
           and f != current_script
    ]
    script_files.sort()
    return script_files

def prompt_selection(files):
    print("Select a file to convert to .txt:")
    print("0: *ALL*")
    for idx, filename in enumerate(files, start=1):
        print(f"{idx}: {filename}")
    while True:
        try:
            selection = int(input("Enter the number of your selection: "))
            if 0 <= selection <= len(files):
                return selection
            else:
                print("Invalid selection. Try again.")
        except ValueError:
            print("Invalid input. Enter a number.")

def get_output_filename(default_name):
    filename = default_name
    while os.path.exists(filename):
        filename = input(f"File '{filename}' already exists. Enter a new filename (with .txt): ").strip()
    return filename

def process_single_file(filename):
    base, _ = os.path.splitext(filename)
    txt_filename = get_output_filename(f"{base}.txt")
    with open(filename, 'r', encoding='utf-8') as src, \
         open(txt_filename, 'w', encoding='utf-8', newline='\n') as dst:
        dst.write(src.read())
    print(f"Created '{txt_filename}'")

def process_all_files(files):
    output_filename = get_output_filename('combined_scripts.txt')
    with open(output_filename, 'w', encoding='utf-8', newline='\n') as dst:
        # Write the list of filenames
        dst.write("Files included:\n")
        for f in files:
            dst.write(f"{f}\n")
        dst.write("\n")
        
        for idx, f in enumerate(files):
            base, _ = os.path.splitext(f)
            dst.write(f"{f}:\n")
            with open(f, 'r', encoding='utf-8') as src:
                dst.write(src.read())
            if idx < len(files) - 1:
                dst.write("\n\n\n")  # 3 newlines between files
    print(f"Created '{output_filename}'")

def main():
    files = list_script_files()
    if not files:
        print("No .py or .sh files found in the current directory.")
        return
    
    selection = prompt_selection(files)
    if selection == 0:
        process_all_files(files)
    else:
        process_single_file(files[selection - 1])

if __name__ == "__main__":
    main()
