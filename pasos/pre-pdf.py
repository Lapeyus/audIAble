# Importing required libraries
import argparse
import os
from PyPDF2 import PdfReader
import fitz

# Function to split pages from a PDF and save as text files
def split_pages_from_pdf(pdf_path, output_folder, pages):
    try:
        # Open the PDF file
        with open(pdf_path, 'rb') as file:
            reader = PdfReader(file)
            # If no specific pages are provided, process all pages
            if not pages:
                pages = list(range(len(reader.pages)))

            # Loop through each page
            for page_num in pages:
                page = reader.pages[page_num]
                # Extract text from the page
                text = page.extract_text()
                cleaned_text = text  # text.replace("", "")

                # Construct the output file path
                output_file_path = os.path.join(output_folder, f'pag_{page_num+1}.txt')
                # Write the extracted text to the output file
                with open(output_file_path, 'w') as output_file:
                    output_file.write(cleaned_text)
                print(f'Text from pag {page_num+1} extracted and saved to {output_file_path}')
    except Exception as e:
        print(f'An error occurred: {e}')


# Function to convert pages from a PDF to images
def pdf_to_images(pdf_path, output_folder, pages):
    try:
        # Open the PDF document
        doc = fitz.open(pdf_path)
        # If no specific pages are provided, process all pages
        if not pages:
            pages = list(range(len(doc)))

        # Loop through each page
        for page_num in pages:
            page = doc[page_num]
            # Convert the page to an image
            img = page.get_pixmap()
            # Save the image to the output folder
            img.save(os.path.join(output_folder, f'pag_{page_num}.png'))
        print(f'PDF converted to images and saved to {output_folder}')
    except Exception as e:
        print(f'An error occurred: {e}')


# Function to parse the pages argument
def parse_pages_argument(pages_str):
    # If a range of pages is provided
    if '-' in pages_str:
        start, end = map(int, pages_str.split('-'))
        return list(range(start-1, end))
    # If specific pages are provided
    elif ',' in pages_str:
        return list(map(lambda x: int(x) - 1, pages_str.split(',')))
    else:
        return [int(pages_str) - 1]


# Main function to handle command line arguments and call the appropriate function
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='PDF Processing')
    # Add command line arguments for the pages, PDF file path, output folder, and mode
    parser.add_argument('--p', help='Pages to be processed (1,2,3 or 1-5)', type=str)
    parser.add_argument('--f', help='PDF file path', type=str, required=True)
    parser.add_argument('--o', help='Output folder', type=str, required=True)
    parser.add_argument('--m', help='Mode (split/photo)', type=str, required=True)

    # Parse the command line arguments
    args = parser.parse_args()

    # Check if the mode is valid
    if args.m not in ['split', 'photo']:
        print("Invalid mode. Use 'split' or 'photo'")
        exit(1)

    # Parse the pages argument if provided
    if args.p:
        pages = parse_pages_argument(args.p)
    else:
        pages = None

    # Create the output folder if it doesn't exist
    if not os.path.exists(args.o):
        os.makedirs(args.o)

    # Call the appropriate function based on the mode
    if args.m == 'split':
        split_pages_from_pdf(args.f, args.o, pages)
    elif args.m == 'photo':
        pdf_to_images(args.f, args.o, pages)
