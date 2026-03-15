import os
import sys
try:
    from escpos.printer import Win32Raw
except ImportError:
    print("Error: python-escpos is not installed correctly.")
    sys.exit(1)

def test_exotic_cuts():
    print("Testing Exotic Cut Variations on 80C Printer...")
    printer_name = "POS-80C"
    
    try:
        printer = Win32Raw(printer_name)
        print("Connected successfully!")
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    def test_cmd(label, hex_bytes):
        print(f"Testing: {label}...")
        printer.text(f"\n--- Testing {label} ---\n")
        printer.text("If this works, the paper should be FULLY cut below.\n")
        printer.text("\n" * 8)
        printer._raw(hex_bytes)
        print(f"Sent {label} command.")

    try:
        # 1. GS V 2 (Some manufacturers use 2 for Full)
        test_cmd("GS V 2 (Alt Full)", b"\x1d\x56\x02")
        
        # 2. ESC V (Legacy)
        test_cmd("ESC V 1", b"\x1b\x56\x01")
        
        # 3. ESC d n (Feed and Cut - if printer supports)
        test_cmd("ESC d 3", b"\x1b\x64\x03")
        
        # 4. Character based cut (Some clones use specific ASCII)
        test_cmd("ASCII GS V '0'", b"\x1d\x560") 

        print("\nTest sequence complete. Please check the results.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        printer.close()

if __name__ == "__main__":
    test_exotic_cuts()
