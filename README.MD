# Google Text-to-Speech Audio Generator

## Overview
This script converts text files to audio using Google's Text-to-Speech API. It takes text files from an input folder and saves the generated audio files into an output folder. The script is configurable, allowing you to specify the voice, audio encoding, and other features for the generated audio.

## Requirements
- Python 3.x
- Google Cloud Platform account
- Google Cloud Text-to-Speech API credentials
- `google-cloud-texttospeech` Python package

## Installation
Install the required Python package by running:
```bash
pip install google-cloud-texttospeech
```

## Configuration
1. Download your Google Cloud API JSON credential file.
2. Place your Google Cloud API JSON credential file in the project root and rename it to `credentials.json`.
3. Update the `config.json` file to set your desired voice and audio configurations.

## Usage
1. Place your text files into an input folder.
2. Run the script with the following command-line arguments:
    ```bash
    python script.py --f <path-to-folder-containing-text-files> --o <path-to-folder-to-save-generated-audio-files>
    ```
   - `--f`: Folder containing the text files to be processed.
   - `--o`: Folder to save the generated audio files.

the pdf processing script has two modes: split creates a TXT file for each one of the pages in the range, and the other mode PHOTO, creates one image for each one of the pages in the selected range.


   - `--m`: mode: create a txt or a photo for each page in the pdf (photo is meant as preparation step for to use OCR)
   - `--p`: pages to be processed. can be a single page, comma separated list or a range using -


For example:
```bash
python3 pre-pdf.py --f book.pdf --o ./cap1 --m split --p 19-43
python3 pre-pdf.py --f book.pdf --o ./cap1 --m photo --p 19-43
python3 pre-cleanup.py --f cap1/txt_files/
python3 pro-gcp-ocr.py  --f cap1/img/ --o cap1/ocr
python3 pro-gcp-tts.py  --f cap1/ocr/ --o cap1/audio
```

## Features
- Command-line interface for easy execution.
- Ability to split large text into smaller parts to manage Text-to-Speech API limitations.
- Checks for existing audio files to avoid redundant processing.
- Audio properties like pitch and speed are customizable via the `config.json` file.

## Function Overview
- `split_text()`: Splits text into smaller parts.
- `generate_text_audio()`: Generates audio for a specific text file.
- `generate_audio()`: Driver function to process all text files in the input folder.


## Inline Comments from Code Files

### pro-gcp-ocr.py

- Configuring Google Cloud Platform credentials
- Parsing command line arguments
- Importing required libraries
- Setting up Google Cloud Platform credentials
- Setting up command line arguments
- Initializing Vision client
- Setting up file directories
- Creating output directory if it doesn't exist
- Loading JSON configurations
- Function to process images and generate text files
- Iterating over each image in the input folder
- Processing only jpg and png images
- Processing the image only if its corresponding text file doesn't exist
- Opening the image file
- Using the Vision API to detect text in the image
- Extracting the detected text
- Writing the extracted text to a file
- Calling the function to process images

### pre-pdf.py

- Importing required libraries
- Function to split pages from a PDF and save as text files
- Opening the PDF file
- If no specific pages are provided, processing all pages
- Looping through each page
- Extracting text from the page
- Constructing the output file path
- Writing the extracted text to the output file
- Function to convert pages from a PDF to images
- Opening the PDF document
- If no specific pages are provided, processing all pages
- Looping through each page
- Converting the page to an image
- Saving the image to the output folder
- Function to parse the pages argument
- If a range of pages is provided
- If specific pages are provided
- Main function to handle command line arguments and call the appropriate function
- Adding command line arguments for the pages, PDF file path, output folder, and mode
- Parsing the command line arguments
- Checking if the mode is valid
- Parsing the pages argument if provided
- Creating the output folder if it doesn't exist
- Calling the appropriate function based on the mode

### pre-cleanup.py

- Importing required libraries
- Function to process all text files in a directory
- Looping through each file in the directory
- Checking if the file is a text file
- Constructing the full filepath
- Opening and reading the file
- Using BeautifulSoup to clean up HTML tags in the text
- Using NLTK for sentence tokenization
- Combining sentences with two line breaks for new paragraphs
- Various text clean-up operations for TTS
- - Removing hyphens between words
- - Replacing multiple spaces with a single space
- - Removing space before commas
-- Replacing '&' with 'and'
- Writing the cleaned up text back to the file
- Printing a success message when all files have been processed
- Printing an error message if something goes wrong
- Main function to handle command line arguments and call the processing function
- Adding a command line argument for the directory path
- Parsing the command line arguments
- Calling the processing function with the directory path argument

### pro-gcp-tts.py

- Importing required libraries
- Setting up Google Cloud Platform credentials
- Setting up command line arguments
- Initializing Text-to-Speech client
- Setting up file directories
- Creating output folder if it does not exist
- Loading JSON configurations
- Function to split text into parts of maximum size max_bytes
- Function to generate audio from a text file
- Iterating over each part of the text
- Skipping the part if its corresponding audio file already exists
- Setting up the input text, voice and audio configuration for the Text-to-Speech API
- Using the Text-to-Speech API to synthesize speech
- Writing the synthesized speech to an audio file
- Function to generate audio from all text files in the input folder
- Running the function to generate audio

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License
This project is licensed under the MIT License.
