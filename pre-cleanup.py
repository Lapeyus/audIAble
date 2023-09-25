import argparse
import os
import re
from bs4 import BeautifulSoup
from num2words import num2words
from nltk.tokenize import sent_tokenize

def process_files_in_directory(directory_path):
    try:
        for filename in os.listdir(directory_path):
            if filename.endswith('.txt'):
                filepath = os.path.join(directory_path, filename)

                with open(filepath, 'r', encoding='utf-8') as file:
                    text = file.read()

                # Use BeautifulSoup to clean up HTML tags
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
                text = re.sub(r'(?<=[a-zA-Z])\s*[-‐]\s*(?=[a-zA-Z])', '', text)
                text = re.sub(r' +', ' ', text)
                text = re.sub(r' ,', ',', text)
                text = text.replace('&', 'and')

                with open(filepath, 'w', encoding='utf-8') as file:
                    file.write(text)
                    print(filepath)

        print('All files have been processed.')
    except Exception as e:
        print(f'An error occurred: {e}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process text files in a directory')
    parser.add_argument('--f', help='Directory path', type=str, required=True)

    args = parser.parse_args()
    process_files_in_directory(args.f)
