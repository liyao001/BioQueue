from cluster_model import ClusterModel

class TorquePBS(ClusterModel):
    pbs_trace_id = 0
    step_id = 0

    def alter_attribute(self, attribute):
        import subprocess
        try:
            parameter = ['qalter']
            parameter.extend(attribute)
            parameter.append(str(self.pbs_trace_id))

            step_process = subprocess.Popen(parameter, shell=False, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)
            stdout, stderr = step_process.communicate()
            return 1
        except Exception, e:
            print e
            return 0

    def cancel_job(self):
        import subprocess
        try:
            step_process = subprocess.Popen(('qdel', str(self.pbs_trace_id)), shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            stdout, stderr = step_process.communicate()
            return 1
        except Exception, e:
            print e
            return 0

    def get_cluster_status(self):
        import subprocess
        import re
        cluster_status = dict()
        try:
            step_process = subprocess.Popen(('pbsnodes',), shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            stdout, stderr = step_process.communicate()
            nodes = stdout.split('\n\n')
            load_pattern = re.compile('loadave=([+-]?\\d*\\.\\d+)(?![-+0-9\\.]),', re.IGNORECASE | re.DOTALL)
            memory_pattern = re.compile('availmem=(\\d+)kb,', re.IGNORECASE | re.DOTALL)
            total_memory_pattern = re.compile('totmem=(\\d+)kb,', re.IGNORECASE | re.DOTALL)
            for node in nodes:
                node_status = dict()
                load_m = load_pattern.search(node)
                if load_m:
                    node_status['load'] = float(load_m.group(1))
                mem_m = memory_pattern.search(node)
                if mem_m:
                    node_status['memav'] = int(mem_m.group(1)) * 1024
                totmem_m = total_memory_pattern.search(node)
                if totmem_m:
                    node_status['memtol'] = int(totmem_m.group(1)) * 1024
                node_name = node.split('\n')[0]
                cluster_status[node_name] = node_status
        except Exception, e:
            print e
        return cluster_status

    def hold_job(self):
        import subprocess
        try:
            step_process = subprocess.Popen(('qhold', str(self.pbs_trace_id)), shell=False, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)
            stdout, stderr = step_process.communicate()
            return 1
        except Exception, e:
            print e
            return 0

    def load_template(self):
        import os
        with open(os.path.join(os.path.split(os.path.realpath(__file__))[0], 'torque_pbs.tpl'), 'r') as file_handler:
            template = file_handler.read()
        return template

    def query_job_status(self):
        import subprocess
        import re
        step_process = subprocess.Popen(('qstat', '-f', str(self.pbs_trace_id)), shell=False, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT)
        stdout, stderr = step_process.communicate()
        status_pattern = re.compile('job_state\\s+=\\s+(.)', re.IGNORECASE | re.DOTALL)
        status_m = status_pattern.search(stdout)
        if status_m:
            raw_code = status_m.group(1)
            if raw_code == 'R':
                return self.step_id
            elif raw_code == 'Q':
                return 0
            elif raw_code == 'C':
                return -1
        else:
            return -3

    def release_job(self):
        import subprocess
        try:
            step_process = subprocess.Popen(('qrls', str(self.pbs_trace_id)), shell=False, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)
            stdout, stderr = step_process.communicate()
            return 1
        except Exception, e:
            print e
            return 0

    def submit_job(self, protocol, job_id, job_step, cpu=0, mem='', queue='', workspace=''):
        import subprocess
        self.step_id = job_step
        template = self.load_template()
        job_name = str(job_id)+'-'+str(job_step)+'.pbs'
        pbs_script_content = template.replace('{PROTOCOL}', protocol).replace('{JOBNAME}', job_name).replace('{GLOBAL_MAX_CPU_FOR_CLUSTER}', str(cpu)).replace('{MEM}', mem+',').replace('{DEFAULT_QUEUE}', queue).replace('{WORKSPACE}', workspace)
        try:
            with open(job_name, 'w') as pbs_handler:
                pbs_handler.write(pbs_script_content)
            step_process = subprocess.Popen(('qsub', job_name), shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            stdout, stderr = step_process.communicate()
            self.pbs_trace_id = stdout.split('\n')[0]
            return self.pbs_trace_id
        except Exception, e:
            print e
            return 0
