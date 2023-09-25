import argparse
import os
from PyPDF2 import PdfReader
import fitz

def split_pages_from_pdf(pdf_path, output_folder, pages):
    try:
        with open(pdf_path, 'rb') as file:
            reader = PdfReader(file)
            if not pages:
                pages = list(range(len(reader.pages)))

            for page_num in pages:
                page = reader.pages[page_num]
                text = page.extract_text()
                cleaned_text = text  # text.replace("", "")

                output_file_path = os.path.join(output_folder, f'pag_{page_num+1}.txt')
                with open(output_file_path, 'w') as output_file:
                    output_file.write(cleaned_text)
                print(f'Text from pag {page_num+1} extracted and saved to {output_file_path}')
    except Exception as e:
        print(f'An error occurred: {e}')

def pdf_to_images(pdf_path, output_folder, pages):
    try:
        doc = fitz.open(pdf_path)
        if not pages:
            pages = list(range(len(doc)))

        for page_num in pages:
            page = doc[page_num]
            img = page.get_pixmap()
            img.save(os.path.join(output_folder, f'pag_{page_num}.png'))
        print(f'PDF converted to images and saved to {output_folder}')
    except Exception as e:
        print(f'An error occurred: {e}')

def parse_pages_argument(pages_str):
    if '-' in pages_str:
        start, end = map(int, pages_str.split('-'))
        return list(range(start-1, end))
    elif ',' in pages_str:
        return list(map(lambda x: int(x) - 1, pages_str.split(',')))
    else:
        return [int(pages_str) - 1]

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='PDF Processing')
    parser.add_argument('--p', help='Pages to be processed (1,2,3 or 1-5)', type=str)
    parser.add_argument('--f', help='PDF file path', type=str, required=True)
    parser.add_argument('--o', help='Output folder', type=str, required=True)
    parser.add_argument('--m', help='Mode (split/photo)', type=str, required=True)

    args = parser.parse_args()

    if args.m not in ['split', 'photo']:
        print("Invalid mode. Use 'split' or 'photo'")
        exit(1)

    if args.p:
        pages = parse_pages_argument(args.p)
    else:
        pages = None

    if not os.path.exists(args.o):
        os.makedirs(args.o)

    if args.m == 'split':
        split_pages_from_pdf(args.f, args.o, pages)
    elif args.m == 'photo':
        pdf_to_images(args.f, args.o, pages)
