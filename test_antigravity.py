from orchestrator.antigravity_client import AntigravityClient, ClaudeCodeError

def main():
    print("Testing Antigravity CLI...")
    try:
        client = AntigravityClient()
        client.launch()
        print("Successfully launched Antigravity!")
        
        # Test a simple command
        result = client.run_step("echo Hello from Antigravity!", timeout=30)
        print("\n--- Output ---")
        print(result)
        print("--------------")
        
    except Exception as e:
        print(f"Error testing Antigravity: {e}")
    finally:
        if 'client' in locals() and client:
            client.close()

if __name__ == "__main__":
    main()
