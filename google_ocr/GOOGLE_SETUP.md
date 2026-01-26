# Google Cloud Vision API Setup Guide

To use the Google Vision API, you need to set up a Google Cloud Project and create a Service Account.

## 1. Create a Google Cloud Project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project drop-down and select **New Project**.
3. Enter a name for your project (e.g., `ocr-service`) and click **Create**.

## 2. Enable Cloud Vision API

1. In the left sidebar, navigate to **APIs & Services** > **Library**.
2. Search for **"Cloud Vision API"**.
3. Click on **Cloud Vision API** and then click **Enable**.

## 3. Create a Service Account

1. Navigate to **IAM & Admin** > **Service Accounts**.
2. Click **+ Create Service Account**.
3. **Step 1**: Enter a name (e.g., `ocr-worker`) and description. Click **Create and Continue**.
4. **Step 2**: Select the role **Cloud Vision** > **Cloud Vision API User**. Click **Continue**.
5. **Step 3**: Click **Done**.

## 4. Generate JSON Key

1. In the list of service accounts, click on the email address of the account you just created.
2. Go to the **Keys** tab.
3. Click **Add Key** > **Create new key**.
4. Select **JSON** and click **Create**.
5. A JSON file will be downloaded to your computer.

## 5. Deployment

1. Rename the downloaded file to `service_account.json` (or any name you prefer).
2. Place this file in the root directory of the `google_ocr` project: `/home/naoufel/projects/AO_scrape/google_ocr/service_account.json`.
3. Ensure your `.env` file (or `config.py`) points to this file.
