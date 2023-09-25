# Importing required libraries
import argparse
import os
import re
from bs4 import BeautifulSoup
from nltk.tokenize import sent_tokenize

# Function to process all text files in a directory
def process_files_in_directory(directory_path):
    try:
        # Loop through each file in the directory
        for filename in os.listdir(directory_path):
            # Check if the file is a text file
            if filename.endswith('.txt'):
                # Construct the full filepath
                filepath = os.path.join(directory_path, filename)

                # Open and read the file
                with open(filepath, 'r', encoding='utf-8') as file:
                    text = file.read()

                # Use BeautifulSoup to clean up HTML tags in the text
                soup = BeautifulSoup(text, 'html.parser')
                text = soup.get_text()

                # Use NLTK for sentence tokenization
                sentences = sent_tokenize(text)

                # Combine sentences with two line breaks for new paragraphs
                text = '\n\n'.join(sentences)

                # Various text clean-up operations for TTS
                text = text.replace('e.g.,', 'for example')
                text = text.replace('Dr.', 'Doctor')
                text = text.replace('St.', 'Street')
                text = text.replace('pp.', 'pages')
                text = text.replace('p.', 'page')
                # Remove hyphens between words
                text = re.sub(r'(?<=[a-zA-Z])\s*[-‐]\s*(?=[a-zA-Z])', '', text)
                # Replace multiple spaces with a single space
                text = re.sub(r' +', ' ', text)
                # Remove space before commas
                text = re.sub(r' ,', ',', text)
                # Replace '&' with 'and'
                text = text.replace('&', 'and')

                # Write the cleaned up text back to the file
                with open(filepath, 'w', encoding='utf-8') as file:
                    file.write(text)
                    print(filepath)

        # Print a success message when all files have been processed
        print('All files have been processed.')
    except Exception as e:
        # Print an error message if something goes wrong
        print(f'An error occurred: {e}')


# Main function to handle command line arguments and call the processing function
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process text files in a dir')
    # Add a command line argument for the directory path
    parser.add_argument('--f', help='Directory path', type=str, required=True)

    # Parse the command line arguments
    args = parser.parse_args()
    # Call the processing function with the directory path argument
    process_files_in_directory(args.f)
