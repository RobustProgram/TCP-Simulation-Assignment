from colorama import Fore
from colorama import Style
from colorama import init
import sys
import socket
import utility
import time

init()

rec_ip = "127.0.0.1"
rec_port = 5555
rec_data = 'received-test.txt'

if len(sys.argv) >= 2:
    if utility.isstrint(sys.argv[1]):
        rec_port = int(sys.argv[1])
    else:
        print('Error: Port argument is meant to be an integer.')
        exit()

if len(sys.argv) >= 3:
    rec_data = sys.argv[2]

# Set up the socket to listen to using UDP
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((rec_ip, rec_port))

ReceivedPacket = utility.STPPacket()
SendingPacket = utility.STPPacket()
receiver_file_handler = open("Receiver_log.txt", 'w')
utility.create_log_file(receiver_file_handler)

received_segments = {}

# =============================================================
# Getting a data packet that has arrived in tact
# =============================================================
receiver_running = True
connection_established = False
received_data_packet = False

while receiver_running:
    # ---------------------------
    # Waiting to receive a syn packet
    while not received_data_packet:
        print("Listening on {} {}".format(rec_ip, rec_port))
        data, address = sock.recvfrom(1024)  # Buffer size of 1024 bytes

        if ReceivedPacket.break_raw_data(data):
            utility.start_time = time.time()
            utility.write_log("rcv", ReceivedPacket, receiver_file_handler)
            utility.receiver_log_file_summary["segments_received_total"] += 1
            received_data_packet = True
        else:
            print("Received packet was corrupted.")
    received_data_packet = False

    # Get the syn packet, return it with an ACK.
    if ReceivedPacket.syn:
        print("Received syn. Reply with ACK.")
        SendingPacket.reset_flags()
        SendingPacket.syn = True
        SendingPacket.ack = True
        SendingPacket.acknowledge_num = ReceivedPacket.sequence_num + 1
        SendingPacket.assemble_stp_header()

        sock.sendto(SendingPacket.raw, address)
        utility.write_log("snd", SendingPacket, receiver_file_handler)

        SendingPacket.sequence_num += 1
    else:
        continue

    # Now we wait for the client's ACK
    while not received_data_packet:
        data, address = sock.recvfrom(1024)  # Buffer size of 1024 bytes

        if ReceivedPacket.break_raw_data(data):
            received_data_packet = True
            utility.write_log("rcv", ReceivedPacket, receiver_file_handler)
            utility.receiver_log_file_summary["segments_received_total"] += 1
        else:
            print("Received ACK packet was corrupted. Trying again ...")

    if ReceivedPacket.ack:
        print("Received the ACK, establish the connection.")
        connection_established = True

    # ----------------------------------------------------------------------------------------------------
    # CONNECTION IS ESTABLISHED. TALKING WITH CLIENT
    # For this assignment, we are going to immediately accept any data sent by the client to be stored into
    # a file. We will only stop writing to the file when the sender asks us to close the connection.
    output_file_handler = open(rec_data, 'wb')

    while connection_established:
        data, address = sock.recvfrom(1024)
        utility.receiver_log_file_summary["segments_received_total"] += 1

        if ReceivedPacket.break_raw_data(data):
            utility.write_log("rcv", ReceivedPacket, receiver_file_handler)

            if ReceivedPacket.fin:
                connection_established = False
            else:
                # When we receive the client's sequence number, we are going to see that they have previous sent
                # (sequence number) amount of data before this packet. We are then going to increment that
                # sequence number with the number of data received in this current packet and send it back.
                print("Received sequence of, {}".format(ReceivedPacket.sequence_num))

                # Before we write to the output file, we will need to check if this sequence number received was
                # dropped. We will check it with the previous packet we sent out. The previous packet we sent out
                # will tell the client about how we were expecting that packet to arrive.
                if SendingPacket.acknowledge_num != ReceivedPacket.sequence_num:
                    print(Fore.LIGHTRED_EX +
                          "Received packet with SEQ {} but expecting SEQ {}. Retransmit the last packet again\n"
                          .format(ReceivedPacket.sequence_num, SendingPacket.acknowledge_num) +
                          Style.RESET_ALL)
                    SendingPacket.reset_flags()
                    SendingPacket.ack = True
                    sock.sendto(SendingPacket.raw, address)
                    utility.write_log("snd/DA", SendingPacket, receiver_file_handler)
                    utility.receiver_log_file_summary["segments_received"] += 1
                    utility.receiver_log_file_summary["duplicate_ack_sent"] += 1

                    if ReceivedPacket.sequence_num in received_segments:
                        received_segments[ReceivedPacket.sequence_num] += 1
                    else:
                        received_segments[ReceivedPacket.sequence_num] = 1
                else:
                    output_file_handler.write(ReceivedPacket.payload)
                    utility.receiver_log_file_summary["data_received"] += len(ReceivedPacket.payload)
                    utility.receiver_log_file_summary["segments_received"] += 1
                    SendingPacket.reset_flags()
                    SendingPacket.ack = True
                    SendingPacket.acknowledge_num = ReceivedPacket.sequence_num + len(ReceivedPacket.payload)
                    SendingPacket.assemble_stp_header()
                    print(Fore.GREEN +
                          "Data looks good. Sending packet with ACK {}\n"
                          .format(SendingPacket.acknowledge_num) +
                          Style.RESET_ALL)
                    sock.sendto(SendingPacket.raw, address)
                    utility.write_log("snd", SendingPacket, receiver_file_handler)

                    if ReceivedPacket.sequence_num in received_segments:
                        received_segments[ReceivedPacket.sequence_num] += 1
                    else:
                        received_segments[ReceivedPacket.sequence_num] = 1
        else:
            print(Fore.LIGHTRED_EX + "Received ACK packet was corrupted. Trying again ...\n" + Style.RESET_ALL)
            # sock.sendto(SendingPacket.raw, address)
            # utility.write_log("snd/DA", SendingPacket, "Receiver_log.txt")
            utility.write_log("rcv/corr", ReceivedPacket, receiver_file_handler)
            utility.receiver_log_file_summary["segments_corrupt"] += 1

    # We have exit out the loop, that means we are going to shut down the system. Since we are assuming the
    # handshakes are perfect, we can close it outside the loop.
    # Received FIN, send the ACK.
    print("Received FIN packet. Closing connection.")
    print("Received sequence of, {}".format(ReceivedPacket.sequence_num))
    SendingPacket.reset_flags()
    SendingPacket.ack = True
    # We are adding one byte to the acknowledge number as the FIN flag consumes 1 byte
    SendingPacket.acknowledge_num = ReceivedPacket.sequence_num + 1
    SendingPacket.assemble_stp_header()
    sock.sendto(SendingPacket.raw, address)
    utility.write_log("snd", SendingPacket, receiver_file_handler)

    # Close the application that needs the TCP connection and wait for it to close
    output_file_handler.close()

    # Application has shut down, time to send the fin to the client.
    SendingPacket.reset_flags()
    SendingPacket.fin = True
    SendingPacket.assemble_stp_header()
    sock.sendto(SendingPacket.raw, address)
    utility.write_log("snd", SendingPacket, receiver_file_handler)

    # Receive the client's ACK to close the connection.
    while True:
        data, address = sock.recvfrom(1024)
        utility.receiver_log_file_summary["segments_received_total"] += 1
        if ReceivedPacket.break_raw_data(data):
            utility.write_log("rcv", ReceivedPacket, receiver_file_handler)
            break
        else:
            print("Received corrupted data. Ignore!")

    print("Receiver successfully has closed the connection.\n")

    for key, value in received_segments.items():
        if value > 1:
            utility.receiver_log_file_summary["segments_duplicate"] += 1

    utility.write_receiver_summary(receiver_file_handler)
    receiver_file_handler.close()
    break